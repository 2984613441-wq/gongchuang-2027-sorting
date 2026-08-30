#!/usr/bin/env python3
"""树莓派端真实链路组装示例（可直接运行的入口骨架）。

本文件把电控侧已就绪的主机闭环模块组装成一条真实链路：
串口（PySerialLink）→ 入站网关（PiProtocolGateway）→ 调度器（Scheduler）
→ 出站网关（OutboundGateway）→ HDMI 渲染（HdmiDisplayRenderer）。

组装结构::

    PySerialLink(port, baud=115200)            # 真实 UART（STM32 USART2 冻结 115200 8N1）
      ├─ 入站: link.receive() 整帧 → PiProtocolGateway.feed_frame → Scheduler
      └─ 出站: OutboundGateway.send_item_task / send_display_ack → link.send()
    Scheduler(FakeTaskSource)                  # 视觉数据源占位（MaixCAM 线格式未冻结）
      └─ 显示: HdmiDisplayRenderer.present(view).complete() → accept_render_receipt

主循环（每件物料）::

    scheduler.next_task()
      → outbound.send_item_task(task)                      # ITEM_TASK 出站
      → 轮询 link.receive() → gateway.feed_frame(frame)
          MOTION_DONE → gateway 已调用 scheduler.accept_motion_done
          ITEM_RESULT → gateway 已调用 scheduler.accept_item_result
          ACK / NACK → 当前 gateway 未建模，事件为 IGNORED，记录后继续
      → build_display_view(content, names)
      → renderer.present(view).complete()                  # PendingRender → RenderReceipt
      → scheduler.accept_render_receipt(receipt)
      → outbound.send_display_ack(intent)                  # DISPLAY_ACK 出站
      → 下一件（赛题 R-D04：显示完成后才能继续）

不写死：
  * 视觉数据源 —— 用 FakeTaskSource 占位；MaixCAM 的 BATCH_TARGETS 线格式冻结后，
    替换为注入的视觉源（见 build_placeholder_source 注释），调度器只认
    set_permitted()/next_if_permitted() 接口，替换无需改动本文件其余部分；
  * 图片目录 / 中文字体 / 名称映射 / 帧输出 —— 一律命令行参数注入；
  * 波特率 115200 为已冻结的 STM32 USART2 配置，仅作默认值（--baud 可改）。

部署：把 电控/src 加入 PYTHONPATH（install.sh 会把该路径写入 venv 的 .pth，
README.md 有说明），本文件所有 import 均为 electrical_control.rpi.*。

开发 / 冒烟：加 --fake-link 使用 FakeSerialLink + 模拟 STM32，无需任何硬件即可
在主机上跑通整条闭环（用于验证组装正确性；不是生产路径）。
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import os
import sys
import time
from pathlib import Path

from electrical_control.protocol import (
    Command,
    Device,
    OuterFrame,
    VERSION,
    encode_outer_frame,
)
from electrical_control.rpi import (
    BatchTargets,
    FakeTaskSource,
    ItemTaskContext,
    Scheduler,
    SchedulerState,
    VerifiedNewRound,
    VisionTarget,
    build_item_task_queue,
)
from electrical_control.rpi.display import build_display_view
from electrical_control.rpi.display_hdmi import HdmiDisplayRenderer
from electrical_control.rpi.gateway import PiProtocolGateway
from electrical_control.rpi.log import (
    DISPLAY,
    FAULT,
    STAGE,
    STARTUP,
    TASK,
    CentralLog,
)
from electrical_control.rpi.outbound import OutboundConfig, OutboundGateway
from electrical_control.rpi.serial_link import FakeSerialLink
from electrical_control.rpi.serial_link_serial import PySerialLink

# ---------------------------------------------------------------------------
# 冻结的部署参数（来自 docs/design/2026-08-29-hdmi-screen-arrival-verification.md）
# 屏规格 1024x600；波特率 115200 为 STM32 USART2 冻结配置（仅作默认值）。
# ---------------------------------------------------------------------------
SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 600

# wqy-zenhei 的标准安装路径（Debian/Raspberry Pi OS）；仅当文件存在时使用。
_WQY_ZENHEI_TTC = "/usr/share/fonts/truetype/wqy/wqy-zenhei/wqy-zenhei.ttc"

# ---------------------------------------------------------------------------
# DEMO 夹具（仅 --fake-link 开发/冒烟模式使用；全部为演示数据，不是冻结参数）
# ---------------------------------------------------------------------------
DEMO_NAMES = {2: "红方柱", 4: "蓝圆柱"}  # class_id -> 货物名称（模拟本地 TF 卡名称表）
DEMO_IMAGE_IDS = {2: 102, 4: 104}  # class_id -> image_id（模拟本地图片 ID 表）
# box_id -> (x, y) 落料点，单位 0.1mm；注入后 ITEM_TASK payload 才可序列化（grip_angle=0xFF）
DEMO_DROP_POINTS = {1: (100, 200), 2: (300, 400)}


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------
def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _env_int(name: str, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    return default if raw is None else int(raw)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="树莓派端真实链路组装示例（电气控制主机侧闭环）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--port",
        default=_env("PORT"),
        help="串口设备（真实模式必填，如 /dev/ttyAMA0；开发模式用 --fake-link）",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=_env_int("BAUD", 115200),
        help="波特率（STM32 USART2 冻结 115200 8N1，作为默认值）",
    )
    parser.add_argument(
        "--image-dir",
        default=_env("IMAGE_DIR"),
        help="TF 卡货物图片目录，按 <image_id>.png/.jpg 命名（真实模式必填）",
    )
    parser.add_argument(
        "--font",
        default=_env("FONT"),
        help="中文字体路径（如 wqy-zenhei）；缺省时提示安装 fonts-wqy-zenhei，"
        "中文将显示为方块",
    )
    parser.add_argument(
        "--names-file",
        default=_env("NAMES_FILE"),
        help="class_id -> 货物名称 的 JSON 映射文件（真实模式必填）",
    )
    parser.add_argument(
        "--round-id",
        default=_env("ROUND_ID"),
        help="本轮 ID（真实模式必填）",
    )
    parser.add_argument(
        "--round-task-id",
        type=int,
        default=_env_int("ROUND_TASK_ID"),
        help="本轮任务号（u16；真实模式必填）",
    )
    parser.add_argument(
        "--start-round",
        action="store_true",
        help="启动时自动开始一轮 verified new round（部署/示例简化；"
        "实赛应按操作员确认流程改造，见 README「当前限制」）",
    )
    parser.add_argument(
        "--frame-output",
        choices=("auto", "fb0", "file", "none"),
        default=_env("FRAME_OUTPUT", "auto"),
        help="合成帧输出方式：fb0 写 /dev/fb0（树莓派，bpp 适配见 README 限制）；"
        "file 存 PNG 到 --output-dir；none 丢弃；auto 自动选择（有 /dev/fb0 用 fb0，否则 none）",
    )
    parser.add_argument(
        "--output-dir",
        default=_env("OUTPUT_DIR", "frames"),
        help="--frame-output file 的 PNG 保存目录",
    )
    parser.add_argument(
        "--fake-link",
        action="store_true",
        help="开发/冒烟模式：FakeSerialLink + 模拟 STM32，无需硬件跑通闭环（非生产路径）",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 日志")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# 注入件工厂：字体 / 名称表 / 图片加载器 / 帧输出 / 视觉源（占位）
# ---------------------------------------------------------------------------
def resolve_font(path: str | None, logger: logging.Logger) -> str | None:
    """解析中文字体路径；缺省时提示安装 fonts-wqy-zenhei（不写死路径）。"""
    if path:
        if not os.path.exists(path):
            raise SystemExit(f"字体文件不存在: {path}")
        return path
    if os.path.exists(_WQY_ZENHEI_TTC):
        return _WQY_ZENHEI_TTC
    logger.warning(
        "未指定 --font 且未找到 wqy-zenhei 字体；中文将显示为方块。"
        "请安装：sudo apt install fonts-wqy-zenhei"
    )
    return None


def load_names(path: str | None, *, demo: bool) -> dict[int, str]:
    """加载 class_id -> 货物名称 映射（树莓派本地 TF 卡名称表）。"""
    if path:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {int(key): str(value) for key, value in data.items()}
    if demo:
        return dict(DEMO_NAMES)
    raise SystemExit(
        "--names-file 必填（真实模式）：class_id -> 名称 的 JSON，"
        '如 {"2": "红方柱", "4": "蓝圆柱"}'
    )


def build_image_loader(image_dir: str | None, *, demo: bool):
    """构造 image_id -> PIL.Image 加载器（TF 卡图片，按 <image_id>.png/.jpg 命名）。

    Pillow 懒加载：本模块 import 不依赖 Pillow 已安装。
    """

    def _load_from_dir(image_id: int):
        from PIL import Image  # 懒加载

        directory = Path(image_dir)
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            candidate = directory / f"{image_id}{ext}"
            if candidate.is_file():
                return Image.open(candidate)
        raise FileNotFoundError(
            f"image_id={image_id} 在 {image_dir} 下未找到（需 <image_id>.png/.jpg）"
        )

    def _demo_placeholder(image_id: int):
        from PIL import Image  # 懒加载

        # 仅开发/冒烟用：生成一张占位色块图，避免依赖真实 TF 卡图片
        return Image.new("RGB", (200, 200), (40 + image_id * 37 % 200, 70, 130))

    if image_dir:
        return _load_from_dir
    if demo:
        return _demo_placeholder
    raise SystemExit("--image-dir 必填（真实模式）：TF 卡货物图片目录")


def build_frame_output(kind: str, output_dir: str, logger: logging.Logger):
    """构造合成帧输出回调（注入 HdmiDisplayRenderer.frame_output）。"""

    if kind == "auto":
        kind = "fb0" if os.path.exists("/dev/fb0") else "none"
        logger.info("--frame-output auto -> %s", kind)

    if kind == "fb0":
        def _to_framebuffer(img) -> None:
            # 最简单的帧缓冲写入（RGB888 原始字节）。
            # ⚠️ 若 framebuffer 是 16bpp（RGB565），需按 FBIOGET_VSCREENINFO 适配 bpp，
            #    见 README「当前限制」；此处仅为可运行的示例。
            with open("/dev/fb0", "wb") as fh:
                fh.write(img.tobytes())

        return _to_framebuffer

    if kind == "file":
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        counter = itertools.count(1)

        def _to_file(img) -> None:
            img.save(directory / f"frame_{next(counter):04d}.png")

        logger.info("合成帧将保存到: %s", directory)
        return _to_file

    if kind == "none":
        return lambda img: None

    raise SystemExit(f"未知 --frame-output: {kind}")


def build_placeholder_source(*, round_id: str, round_task_id: int, demo: bool) -> FakeTaskSource:
    """视觉数据源占位：FakeTaskSource（演示队列）。

    ⚠️ 视觉数据源占位：MaixCAM 的 BATCH_TARGETS 线格式**未冻结**，这里用
    FakeTaskSource 直接喂演示 ItemTaskContext，绝不写死视觉线格式。

    线格式冻结后，把解析出的 BatchTargets 换成注入式视觉源即可，调度器只依赖
    set_permitted()/next_if_permitted() 接口：

        vision_source = FakeVisionSource(parsed_batches)   # 或真实 MaixCAM 解析源
        queue = build_item_task_queue(
            batch,
            image_id_for_class=...,   # class_id -> image_id（本地 TF 卡表）
            drop_point_for_box=...,   # box_id -> (x, y) 落料表（注入后 payload 才可序列化）
        )
        contexts = tuple(
            ItemTaskContext(round_id, round_task_id, frame_seq=10 + i, payload=p)
            for i, p in enumerate(queue)
        )
        scheduler.load_source(FakeTaskSource(contexts))
    """
    if demo:
        batch = BatchTargets(
            round_task_id,
            (
                VisionTarget(1, 2, box_id=1),  # 红方柱（DEMO）
                VisionTarget(2, 4, box_id=2),  # 蓝圆柱（DEMO）
            ),
        )
        queue = build_item_task_queue(
            batch,
            image_id_for_class=DEMO_IMAGE_IDS.__getitem__,
            drop_point_for_box=DEMO_DROP_POINTS.__getitem__,
        )
    else:
        queue = ()  # 真实模式：等待注入视觉源；接入前一轮开始后即为空源（见 README 限制）

    contexts = tuple(
        ItemTaskContext(round_id, round_task_id, frame_seq=10 + index, payload=payload)
        for index, payload in enumerate(queue)
    )
    return FakeTaskSource(contexts)


# ---------------------------------------------------------------------------
# 模拟 STM32（仅 --fake-link 开发/冒烟用）
# ---------------------------------------------------------------------------
def _stm32_frame(
    command: Command, *, frame_seq: int, task_id: int, payload: bytes = b""
) -> bytes:
    """按冻结外层帧协议构造一条 STM32 -> RASPI 帧（模拟固件行为）。"""
    return encode_outer_frame(
        OuterFrame(
            VERSION, Device.STM32, Device.RASPI,
            task_id, frame_seq, int(command), payload,
        )
    )


def _queue_demo_stm32_replies(
    link: FakeSerialLink, task: ItemTaskContext, round_task_id: int,
    motion_seq: int, result_seq: int,
) -> None:
    """模拟 STM32：收到 ITEM_TASK 后回 MOTION_DONE → ITEM_RESULT(SUCCESS)。

    与 电控/tests/integration/test_host_side_chain.py 的模拟器行为一致，
    用于主机上无硬件跑通闭环；真实模式由 STM32 固件经 UART 回复。
    """
    link.queue_inbound(
        _stm32_frame(Command.MOTION_DONE, frame_seq=motion_seq, task_id=round_task_id)
    )
    link.queue_inbound(
        _stm32_frame(
            Command.ITEM_RESULT,
            frame_seq=result_seq,
            task_id=round_task_id,
            payload=bytes((task.payload.target_seq, 0x00, 0x00)),  # result_code=0x00 SUCCESS
        )
    )


# ---------------------------------------------------------------------------
# 显示闭环（ITEM_RESULT 之后：渲染 → 回执 → DISPLAY_ACK）
# ---------------------------------------------------------------------------
def _render_and_ack(
    scheduler: Scheduler,
    outbound: OutboundGateway,
    names: dict[int, str],
    image_loader,
    frame_output,
    font_path: str | None,
    cl: CentralLog,
    logger: logging.Logger,
) -> None:
    task = scheduler.current_task  # 必须先取：accept_render_receipt 会清空 current_task
    content = scheduler.display_model
    if task is None or content is None:
        logger.warning("ITEM_RESULT 已处理但无活动任务/显示内容，跳过渲染")
        return

    view = build_display_view(content, names)  # 解析本地名称（class_id -> 名称）
    renderer = HdmiDisplayRenderer(
        width=SCREEN_WIDTH,
        height=SCREEN_HEIGHT,
        image_loader=image_loader,
        frame_output=frame_output,
        font_path=font_path,
        task=task,  # 构造时注入活动任务，complete() 才能重建正确 DisplayContent/CRC
    )
    pending = renderer.present(view)  # 合成 1024x600 帧 → frame_output（图片缺失会 fail-closed）
    receipt = pending.complete()      # PendingRender.complete() → RenderReceipt（含 content_crc32）
    intent = scheduler.accept_render_receipt(receipt)  # 状态 WAIT_RENDER → READY（R-D04 门禁放行）
    raw_ack = outbound.send_display_ack(intent)        # DISPLAY_ACK 出站（RENDERED）
    cl.record(
        DISPLAY,
        now=time.monotonic(),
        round_id=task.round_id,
        task_id=task.task_id,
        target_seq=view.target_seq,
        success_count=view.success_count,
        detail=f"rendered + DISPLAY_ACK sent ({len(raw_ack)}B)",
    )
    logger.info(
        "显示完成并确认: target_seq=%d name=%s success=%d → DISPLAY_ACK",
        view.target_seq, view.name, view.success_count,
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logger = logging.getLogger("ec-chain")
    cl = CentralLog(capacity=1024)

    demo = bool(args.fake_link)
    if demo:
        round_id = args.round_id or "round-demo"
        round_task_id = args.round_task_id if args.round_task_id is not None else 7
    else:
        if not args.port:
            raise SystemExit("--port 必填（真实模式）；开发模式加 --fake-link")
        if not args.round_id:
            raise SystemExit("--round-id 必填（真实模式）")
        if args.round_task_id is None:
            raise SystemExit("--round-task-id 必填（真实模式）")
        round_id, round_task_id = args.round_id, args.round_task_id

    font_path = resolve_font(args.font, logger)
    names = load_names(args.names_file, demo=demo)
    image_loader = build_image_loader(args.image_dir, demo=demo)
    frame_output = build_frame_output(args.frame_output, args.output_dir, logger)

    # ---- 组装：PySerialLink → (PiProtocolGateway + OutboundGateway + Scheduler) ----
    if demo:
        link = FakeSerialLink()
        logger.warning(
            "--fake-link：FakeSerialLink + 模拟 STM32（仅开发/冒烟，不触碰任何硬件）"
        )
    else:
        link = PySerialLink(args.port, baudrate=args.baud)  # 真实 UART，USART2 115200 8N1
        logger.info("串口已打开: %s @ %d 8N1", args.port, args.baud)

    scheduler = Scheduler()  # 初始 RECOVERY_LOCK：未 verified new round 前不会派发任务
    gateway = PiProtocolGateway(scheduler)  # 入站：feed_frame → Scheduler 门禁
    outbound = OutboundGateway(  # 出站：ITEM_TASK / DISPLAY_ACK（task_id 与 round 严格校验）
        link, config=OutboundConfig(round_task_id=round_task_id)
    )
    scheduler.load_source(
        build_placeholder_source(round_id=round_id, round_task_id=round_task_id, demo=demo)
    )

    if args.start_round or demo:
        # 真实部署中三个独立权威（操作员确认 / STM32 就绪 / 双节点初始化）应来自
        # 人工确认流程与 BARRIER_READY/DEVICE_READY 上报；示例骨架直接置 True
        # （见 README「当前限制」）。三权不全时 start_verified_new_round 抛 PermissionError。
        scheduler.start_verified_new_round(VerifiedNewRound(round_id, True, True, True))
        logger.info("已开始 verified new round: round_id=%s task_id=%d", round_id, round_task_id)

    cl.record(
        STARTUP,
        now=time.monotonic(),
        round_id=round_id,
        detail=(
            f"link={type(link).__name__} port={args.port or 'fake'} "
            f"frame_output={args.frame_output}"
        ),
    )
    logger.info("链路就绪：next_task → send_item_task → 轮询入站 → 渲染 → DISPLAY_ACK")

    # ---- 主循环（select 轮询；可选改造：独立入站线程 + gateway.feed_byte 逐字节）----
    demo_seq = itertools.count(101)  # 模拟 STM32 的入站帧号（仅 demo）
    last_status = 0.0
    done_items = 0

    while True:
        if scheduler.is_faulted:
            cl.record(FAULT, now=time.monotonic(), detail="scheduler FAULT, 链路停止")
            logger.error("scheduler FAULT，链路停止（fail-closed）")
            return 1

        # 1) 派发下一件（R-D04：未完成显示前返回 None）
        task = scheduler.next_task()
        if task is not None:
            raw = outbound.send_item_task(task)  # ITEM_TASK 出站（状态 → WAIT_MOTION_DONE）
            done_items += 1
            cl.record(
                TASK,
                now=time.monotonic(),
                round_id=task.round_id,
                task_id=task.task_id,
                frame_seq=task.frame_seq,
                target_seq=task.payload.target_seq,
                detail=(
                    f"ITEM_TASK sent ({len(raw)}B), "
                    f"class_id={task.payload.class_id} image_id={task.payload.image_id}"
                ),
            )
            logger.info(
                "ITEM_TASK sent: target_seq=%d class_id=%d image_id=%d",
                task.payload.target_seq, task.payload.class_id, task.payload.image_id,
            )
            if demo:
                _queue_demo_stm32_replies(
                    link, task, round_task_id, next(demo_seq), next(demo_seq)
                )
        elif scheduler.state is SchedulerState.READY:
            if scheduler.estop_active:
                cl.record(STAGE, now=time.monotonic(), detail="ESTOP：本轮结束")
                logger.warning("急停已激活，本轮结束，链路停止")
                return 0
            logger.info("任务源已耗尽（当前为占位视觉源），本轮结束")
            break

        # 2) 轮询入站：整帧交给网关分发
        frame = link.receive()
        if frame is None:
            if time.monotonic() - last_status > 10.0:
                logger.info("空闲: state=%s success=%d", scheduler.state.name, scheduler.success_count)
                last_status = time.monotonic()
            time.sleep(0.05)  # 轮询节流（~20Hz；PySerialLink.receive 自带 0.05s 超时）
            continue

        outcome = gateway.feed_frame(frame)
        event = outcome.event

        if event == "MOTION_DONE":
            # gateway 已校验 task_id 并调用 scheduler.accept_motion_done（→ WAIT_ITEM_RESULT）
            logger.info("inbound: MOTION_DONE accepted")
        elif event == "ITEM_RESULT":
            # gateway 已解析 payload 并调用 scheduler.accept_item_result（→ WAIT_RENDER）
            logger.info("inbound: ITEM_RESULT accepted")
            _render_and_ack(scheduler, outbound, names, image_loader,
                            frame_output, font_path, cl, logger)
        elif event == "BARRIER_READY":
            logger.info("inbound: BARRIER_READY（STM32 就绪上报，记录即可）")
        elif event == "ESTOP":
            cl.record(STAGE, now=time.monotonic(), detail="inbound ESTOP")
            logger.warning("inbound: ESTOP（急停，本轮结束）")
        elif event == "FAULT":
            cl.record(FAULT, now=time.monotonic(), detail=outcome.fault)
            logger.error("inbound FAULT: %s", outcome.fault)
        elif event == "DUPLICATE":
            logger.info("inbound: DUPLICATE（重放/重传帧，已用缓存应答）")
        elif event == "IGNORED":
            # ACK/NACK（Command 0x05/0x06）等未建模命令在此出现：记录后继续。
            # STM32 级 ACK/NACK 建模属未来步骤（当前链路以 MOTION_DONE/ITEM_RESULT 驱动）。
            logger.info("inbound: IGNORED（含 ACK/NACK 等未建模命令）")
        else:
            # FRAME_REJECTED / DIRECTION_REJECTED / CRASH / *_IGNORED 等
            logger.warning("inbound %s: %s", event, outcome.fault or "")

    logger.info("本轮汇总: 派发 %d 件, 成功计数 %d", done_items, scheduler.success_count)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\n用户中断，退出", file=sys.stderr)
        return 130
    except Exception as exc:  # fail-closed：入口兜底，避免裸栈
        logging.getLogger("ec-chain").exception("链路异常退出: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
