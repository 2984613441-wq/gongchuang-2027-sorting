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
import configparser
import itertools
import json
import logging
import math
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Callable

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
from electrical_control.rpi.socket_vision_source import (
    SocketVisionSource,
    vision_listener,
)
from electrical_control.rpi.display import build_display_view, split_color_shape
from electrical_control.rpi.display_hdmi import (
    FramebufferFormatError,
    FramebufferFrameOutput,
    HdmiDisplayRenderer,
    TwoStageDisplay,
    TwoStageInfo,
)
from electrical_control.rpi.gateway import PiProtocolGateway
from electrical_control.rpi.drop_strategy import (
    FixedBoxStrategy,
    load_strategy_from_config,
)
from electrical_control.rpi.log import (
    DISPLAY,
    FAULT,
    STAGE,
    STARTUP,
    TASK,
    CentralLog,
)
from electrical_control.rpi.outbound import OutboundConfig, OutboundGateway
from electrical_control.rpi.pixel_to_device import (
    PixelToDeviceConverter,
    make_grasp_point_for_target,
)
from electrical_control.rpi.serial_link import FakeSerialLink
from electrical_control.rpi.serial_link_serial import PySerialLink

# 模块级 logger。main() 里还有一个同名的局部 logger（logging.getLogger("ec-chain")），
# 这里用 _LOGGER 以免遮蔽，且与链路其余日志汇到同一个 logger 名下。
_LOGGER = logging.getLogger("ec-chain")

# ---------------------------------------------------------------------------
# 冻结的部署参数（来自 docs/design/2026-08-29-hdmi-screen-arrival-verification.md）
# 屏规格 1024x600；波特率 115200 为 STM32 USART2 冻结配置（仅作默认值）。
# ---------------------------------------------------------------------------
SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 600

# 监控端口配置
MONITOR_PORT = 9002  # 树莓派监控端口（与MaixCAM的9001区分）

# wqy-zenhei 的标准安装路径（Debian/Raspberry Pi OS）；仅当文件存在时使用。
_WQY_ZENHEI_TTC = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"

# ---------------------------------------------------------------------------
# DEMO 夹具（仅 --fake-link 开发/冒烟模式使用；全部为演示数据，不是冻结参数）
# ---------------------------------------------------------------------------
DEMO_NAMES = {2: "红方柱", 4: "蓝圆柱"}  # class_id -> 货物名称（模拟本地 TF 卡名称表）
DEMO_IMAGE_IDS = {2: 2, 4: 4}  # class_id -> image_id（冻结 image_id == class_id 1:1）
# box_id -> (x, y) 落料点，单位 0.1mm；注入后 ITEM_TASK payload 才可序列化（grip_angle=0xFF）
DEMO_DROP_POINTS = {1: (100, 200), 2: (300, 400)}
# P3（2026-09-16）：target_seq -> (x, y) 抓取点，单位 0.1mm。ITEM_TASK 8→12 字节后
# 抓取点成为必填字段：**没有它就不可序列化**（encode 直接抛错），绝不会退回 (0,0)。
# 这里是纯演示数据（离线 --fake-link 冒烟用），不是标定结果；真实抓取点来自
# 树莓派侧"像素→mm"换算（含高度视差补偿），见台账 H-1。
DEMO_GRASP_POINTS = {1: (-300, 0), 2: (0, 150)}

# 落点表来源（2026-09-15 接线）：真实六盒坐标从 sorting_config.ini 的
# [DropPoints] 读，由 `工具/control_panel.py` 的“对应表”区现场标定后写入。
# ⚠️ 原 BRIDGE_DROP_POINT = (100, 200) 固定占位点已删除 —— 它让**六个盒子
#    全落到同一个点**。真坐标没填齐时 run_chain 直接拒绝启动（fail-closed）。
DEFAULT_CONFIG_PATH = os.environ.get("SORTING_CONFIG", "/home/pi/sorting_config.ini")

# ---------------------------------------------------------------------------
# 监控模块（汇总视觉+电控+执行结果，发送给GUI）
# ---------------------------------------------------------------------------
class MonitorBroadcaster:
    """监控数据广播器：汇总视觉、电控指令、执行结果，发送给GUI客户端"""

    def __init__(self, port: int = MONITOR_PORT):
        self.port = port
        self.clients: list[socket.socket] = []
        self.lock = threading.Lock()
        self.server: socket.socket | None = None
        self.running = False

        # 数据缓存
        self.latest_vision_batch: dict | None = None
        self.latest_item_task: dict | None = None
        self.latest_item_result: dict | None = None

    def start(self, logger: logging.Logger) -> None:
        """启动监控服务器"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind(('0.0.0.0', self.port))
            self.server.listen(5)
            self.server.settimeout(1.0)
            self.running = True

            # 启动接受连接的线程
            accept_thread = threading.Thread(
                target=self._accept_clients,
                args=(logger,),
                name="monitor-accept",
                daemon=True
            )
            accept_thread.start()
            logger.info(f"[MONITOR] 监控服务已启动: 0.0.0.0:{self.port}")
        except Exception as e:
            logger.error(f"[MONITOR] 启动失败: {e}")

    def _accept_clients(self, logger: logging.Logger) -> None:
        """接受客户端连接（独立线程）"""
        while self.running and self.server:
            try:
                client, addr = self.server.accept()
                logger.info(f"[MONITOR] 客户端连接: {addr}")
                with self.lock:
                    self.clients.append(client)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.debug(f"[MONITOR] 接受连接失败: {e}")
                break

    def broadcast(self, data: dict) -> None:
        """向所有客户端广播数据"""
        if not self.clients:
            return

        try:
            message = json.dumps(data).encode() + b'\n'
        except Exception:
            return

        dead_clients = []
        with self.lock:
            for client in self.clients:
                try:
                    client.sendall(message)
                except Exception:
                    dead_clients.append(client)

            for client in dead_clients:
                self.clients.remove(client)
                try:
                    client.close()
                except Exception:
                    pass

    def update_vision(self, batch: BatchTargets) -> None:
        """更新视觉数据"""
        self.latest_vision_batch = {
            'task_id': batch.task_id,
            'targets': [
                {
                    'target_seq': t.target_seq,
                    'class_id': t.class_id,
                    'box_id': t.box_id,
                }
                for t in batch.targets
            ]
        }
        self._send_status()

    def update_item_task(self, task: ItemTaskContext) -> None:
        """更新电控指令"""
        self.latest_item_task = {
            'round_id': task.round_id,
            'task_id': task.task_id,
            'frame_seq': task.frame_seq,
            'target_seq': task.payload.target_seq,
            'class_id': task.payload.class_id,
            'image_id': task.payload.image_id,
            'x_position': task.payload.x_position,
            'y_position': task.payload.y_position,
        }
        self._send_status()

    def update_item_result(self, target_seq: int, result_code: int, basis: int) -> None:
        """更新执行结果"""
        self.latest_item_result = {
            'target_seq': target_seq,
            'result_code': result_code,
            'basis': basis,
            'success': result_code == 0x00,
        }
        self._send_status()

    def _send_status(self) -> None:
        """发送汇总状态"""
        status = {
            'timestamp': time.time(),
            'vision': self.latest_vision_batch,
            'item_task': self.latest_item_task,
            'item_result': self.latest_item_result,
        }
        self.broadcast(status)

    def stop(self) -> None:
        """停止监控服务"""
        self.running = False
        if self.server:
            try:
                self.server.close()
            except Exception:
                pass
        with self.lock:
            for client in self.clients:
                try:
                    client.close()
                except Exception:
                    pass
            self.clients.clear()

def load_fixed_pick_point(path: str | Path) -> tuple[int, int] | None:
    """从 sorting_config.ini 的 [PickPoint] 读**固定抓取点**（单位 mm → 0.1mm）。

    为什么要有这个（2026-09-18 用户裁定）：
    用户决定**每次把物块放在同一个位置**。那样抓取点在装置坐标里就是一个
    **常量**，不再需要像素→毫米标定 —— 视觉只负责"这是什么件"（分类/计数），
    不负责"它在哪"。

    这**不是**"猜一个坐标"（项目明令禁止的那种）：
    · 猜坐标 = 程序在解析失败时自己编一个默认值；
    · 这里 = 操作员在配置里**显式声明**"我们的件就放在这儿"，程序只负责读。
    两者的区别是"谁做的决定"。读不到就返回 None，调用方继续 fail-closed。

    返回 None 的三种情况：文件不存在、没有 [PickPoint] 节、值解析不出来。
    """

    p = Path(path)
    if not p.exists():
        return None
    cfg = configparser.ConfigParser()
    cfg.read(p, encoding="utf-8")
    if not cfg.has_section("PickPoint"):
        return None
    try:
        x_mm = cfg.getfloat("PickPoint", "x")
        y_mm = cfg.getfloat("PickPoint", "y")
    except (configparser.Error, ValueError):
        return None
    if not (math.isfinite(x_mm) and math.isfinite(y_mm)):
        return None
    return (int(round(x_mm * 10)), int(round(y_mm * 10)))


def load_drop_points(path: str | Path) -> dict[int, tuple[int, int]]:
    """从 sorting_config.ini 的 [DropPoints] 读六盒落点。

    文件里单位是 **mm**（`工具/control_panel.py` 按 mm 写），ITEM_TASK 要
    **0.1mm**，这里换算。读不到条目就返回空表 —— 调用方 fail-closed，
    绝不猜坐标：猜错 = 货落错盒，直接违反“形状颜色一致的放同一个盒”。
    """
    p = Path(path)
    if not p.exists():
        return {}
    cfg = configparser.ConfigParser()
    cfg.read(p, encoding="utf-8")
    if not cfg.has_section("DropPoints"):
        return {}
    out: dict[int, tuple[int, int]] = {}
    for key, value in cfg.items("DropPoints"):
        try:
            box_id = int(key)
            x_mm, y_mm = (float(part) for part in value.split(","))
        except ValueError:
            continue
        if 1 <= box_id <= 6:
            out[box_id] = (int(round(x_mm * 10)), int(round(y_mm * 10)))
    return out

def load_box_map(path: str | Path) -> dict[tuple[int, int], int]:
    """从 [BoxMap] 读对应表 (color_id, shape_id) -> box_id。

    对应表**不在本文件里做分配**（视觉侧已给出 box_id）；这里读它是为了做
    一致性校验：对应表用到的每个货格，落点表里都必须有坐标。
    """
    p = Path(path)
    if not p.exists():
        return {}
    cfg = configparser.ConfigParser()
    cfg.read(p, encoding="utf-8")
    if not cfg.has_section("BoxMap"):
        return {}
    out: dict[tuple[int, int], int] = {}
    for key, value in cfg.items("BoxMap"):
        parts = key.split(",")
        if len(parts) != 2:
            continue
        try:
            color_id, shape_id, box_id = int(parts[0]), int(parts[1]), int(value)
        except ValueError:
            continue
        if 1 <= box_id <= 6:
            out[(color_id, shape_id)] = box_id
    return out

def _identity_image_id(class_id: int) -> int:
    return class_id  # image_id == class_id 冻结 1:1

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
        "--calibration-config",
        default=_env("CALIBRATION_CONFIG"),
        help="像素→毫米标定文件（[CameraCalibration]/[ObjectHeights]/"
        "[WorkspaceLimits]）。缺省用 电控/calibration_config.ini；"
        "🔴 未标定/仍是占位值全 0 时抓取点解析不出来，一条 ITEM_TASK 都发不出去",
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
    parser.add_argument(
        "--config",
        default=_env("SORTING_CONFIG", DEFAULT_CONFIG_PATH),
        help="参数配置文件：[DropPoints] 六盒落点 / [BoxMap] 对应表；"
        "由 工具/control_panel.py 现场标定后写入。缺表则拒绝启动",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 日志")
    parser.add_argument(
        "--pick-strategy",
        choices=("off", "order"),
        default=_env("PICK_STRATEGY", "off"),
        help="夹取策略：off=现有贪心最近邻（默认，与接入前逐字节一致）；"
        "order=用 pick_strategy 的离托盘无壁边最近规则选件（只改顺序、不丢件）",
    )
    parser.add_argument(
        "--pick-strategy-config",
        default=_env("PICK_STRATEGY_CONFIG", "/home/pi/电控/deploy/pick_strategy.ini"),
        help="--pick-strategy=order 时的策略配置；缺失或解析失败则自动退回 off",
    )
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

def build_frame_output(
    kind: str, output_dir: str, logger: logging.Logger, *, demo: bool
):
    """构造合成帧输出回调（注入 HdmiDisplayRenderer.frame_output）。

    生产模式（非 --fake-link）必须真的把帧送到屏上：取不到 /dev/fb0 就
    SystemExit，**绝不静默降级为 none**。静默降级的后果是屏全黑但链路照跑、
    DISPLAY_ACK 照发，直接撞赛规"15 秒没有显示本次分拣信息，本轮比赛结束"，
    而且现场看不出任何异常。
    """

    if kind == "auto":
        if not demo:
            raise SystemExit(
                "--frame-output auto 只用于 --fake-link 主机测试。\n"
                "  真实模式必须显式指定 --frame-output fb0（HDMI 屏）；\n"
                "  auto 会在取不到 /dev/fb0 时静默降级为 none —— 屏幕全黑却不报错。"
            )
        kind = "fb0" if os.path.exists("/dev/fb0") else "none"
        logger.info("--frame-output auto -> %s（仅 --fake-link 主机测试）", kind)

    if kind == "fb0":
        try:
            # 启动期就试开一次：权限/设备缺失在此 fail-fast，而不是等第一件
            # 物料走到渲染才炸（那时 STM32 已经动过了）。
            with open("/dev/fb0", "rb"):
                pass
        except OSError as exc:
            raise SystemExit(
                f"打不开 /dev/fb0（{exc}）：拒绝启动。\n"
                "  检查：ls -l /dev/fb0；当前用户是否在 video 组；HDMI 是否已输出。\n"
                "  只想在主机上跑链路请加 --fake-link。"
            ) from exc
        try:
            # 按 fb 的真实 bpp 打包（16bpp→RGB565 小端，24/32bpp→BGR[X]）并处理行填充。
            # 读不到真实 bpp 就 fail-closed —— 按 32bpp 猜的后果已实机踩过：
            # 16bpp 的屏上写 1,843,200 字节 = [Errno 28] No space left on device。
            return FramebufferFrameOutput("/dev/fb0", size=(SCREEN_WIDTH, SCREEN_HEIGHT))
        except FramebufferFormatError as exc:
            raise SystemExit(
                f"/dev/fb0 像素格式读不到，拒绝启动：{exc}\n"
                "  查：cat /sys/class/graphics/fb0/bits_per_pixel "
                "/sys/class/graphics/fb0/virtual_size\n"
                "  自检：python3 -m electrical_control.rpi.display_hdmi --info"
            ) from exc

    if kind == "file":
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        counter = itertools.count(1)

        def _to_file(img) -> None:
            img.save(directory / f"frame_{next(counter):04d}.png")

        logger.info("合成帧将保存到: %s", directory)
        return _to_file

    if kind == "none":
        if not demo:
            logger.warning(
                "--frame-output none：本轮不会有任何屏幕输出。赛规要求本次分拣信息"
                "必须显示，15 秒无显示即判本轮结束 —— 仅调试用，赛场上别用。"
            )
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
            drop_point_for_box=...,   # box_id -> (x, y) 落料表
            grasp_point_for_target=...,  # VisionTarget -> (x, y) 抓取点（像素→mm 换算）
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
            # P3：落料点 + 抓取点都给全，payload 才是可序列化的 12 字节。
            grasp_point_for_target=lambda target: DEMO_GRASP_POINTS.get(target.target_seq),
        )
    else:
        queue = ()  # 真实模式：等待注入视觉源；接入前一轮开始后即为空源（见 README 限制）

    contexts = tuple(
        ItemTaskContext(round_id, round_task_id, frame_seq=10 + index, payload=payload)
        for index, payload in enumerate(queue)
    )
    return FakeTaskSource(contexts)

def make_drop_point_lookup(
    drop_points: dict[int, tuple[int, int]], logger: logging.Logger
) -> Callable[[int], tuple[int, int] | None]:
    """安全落点查表：未知 box_id 返回 None，该件**拒识**，链路继续。

    这里**不能**直接传 `drop_points.__getitem__`：未知 box_id 抛 KeyError 会
    一路冒到 run() 的兜底 `except`，把**整条链**带走（stopped，不是丢一件）。
    返回 None 后由 build_item_task_queue 跳过该件 —— 不进队列、不发 ITEM_TASK。

    注意这**不是**"猜一个点"：拒识该件 ≠ 给一个默认坐标；落点表语义没动，
    六盒坐标仍从 [DropPoints] 读。
    """

    def lookup(box_id: int) -> tuple[int, int] | None:
        point = drop_points.get(box_id)
        if point is None:
            logger.warning(
                "未知 box_id=%r：落点表只有 %s，拒识该件（不进队列、不发 ITEM_TASK）",
                box_id,
                sorted(drop_points),
            )
        return point

    return lookup

def build_socket_source(
    *,
    round_id: str,
    round_task_id: int,
    drop_point_for_box: Callable[[int], tuple[int, int] | None],
    calibration_config: str | Path | None = None,
    fixed_pick_point: tuple[int, int] | None = None,
    payload_orderer: Callable[[tuple[object, ...]], tuple[object, ...]] | None = None,
) -> SocketVisionSource:
    """真实视觉源：SocketVisionSource + **真实落点表** + **真实像素→毫米标定**。

    落点表来自 sorting_config.ini 的 [DropPoints]（见 load_drop_points），
    由 `工具/control_panel.py` 现场标定后写入。查不到的 box_id 返回 None，
    由 build_item_task_queue 跳过该件（拒识并记日志）—— 既不猜点，也不因为
    一件查不到就把整条链带走。见 P11-A 设计 §1.3。

    抓取点来自 calibration_config.ini 的 [CameraCalibration]（像素→毫米仿射
    + 高度视差补偿），由 `工具/calib_photo.py` 或 `工具/calib_affine.py` 产出。

    🔴 2026-09-18 接通（此前一直是断的）：
    本函数原先**没有**传 grasp_point_for_target，于是 pick_x/pick_y 恒为 None，
    `encode_item_task_payload` 抛 PayloadError（item_context.py:131），
    **一条 ITEM_TASK 都发不出去、机器一步都不会动**。
    件本身的 box_id 是有的（校赛模式把颜色折叠进 BATCH_TARGETS 的 id 字节，
    见 vision_ingest.BATCH_ID_BYTE_IS_BOX_ID），所以缺的只有这一个。

    ⚠️ 未标定（参数缺失、仍是占位值全 0、或矩阵不可逆）时
    `make_grasp_point_for_target` 一律返回 None → 该件被拒识 → 链路继续但不产出。
    这是有意的 fail-closed：宁可不出货，也不要拿 (0,0) 把每一件都送到正中。
    """
    converter = PixelToDeviceConverter(calibration_config)
    if converter.is_calibrated:
        _LOGGER.info(
            "抓取点来源 = 像素→毫米标定 %s（工作区 [%.1f,%.1f]×[%.1f,%.1f]mm，"
            "物体高度 %d 类）",
            converter.config_path,
            converter.x_limits[0], converter.x_limits[1],
            converter.y_limits[0], converter.y_limits[1],
            len(converter.object_heights),
        )
        grasp_point_for_target = make_grasp_point_for_target(converter)
    elif fixed_pick_point is not None:
        # 固定摆放模式（2026-09-18 用户裁定）：件每次都放在同一个位置，
        # 抓取点是常量，不需要像素→毫米标定。
        _LOGGER.warning(
            "标定未加载（%s）→ 改用【固定抓取点】模式：[PickPoint] = "
            "(%.1f, %.1f)mm。**件必须每次放在同一位置**，"
            "否则会抓空或抓偏。",
            converter.config_path,
            fixed_pick_point[0] / 10.0, fixed_pick_point[1] / 10.0,
        )

        def grasp_point_for_target(target):
            return fixed_pick_point

    else:
        _LOGGER.error(
            "抓取点来源缺失：标定未加载（%s）且 sorting_config.ini 没有 [PickPoint]。"
            "本次运行**不会产出任何 ITEM_TASK**、机器不会动。"
            "二选一：(a) 做像素→毫米标定填进 calibration_config.ini；"
            "(b) 在 sorting_config.ini 写一节 [PickPoint] x=.. y=..（mm，件固定放一处）。",
            converter.config_path,
        )
        # ⚠️ 这里必须给一个**总是返回 None 的回调**，不能真的传 None。
        #    vision_ingest.py:240 的语义是：
        #      回调为 None   → pick 留 None，该件**照样进队列**，
        #                      直到 encode_item_task_payload 才抛 PayloadError；
        #      回调返回 None → **当场拒识该件**（continue），不进队列。
        #    我们要的是后者：没有抓取点来源时一帧就干脆不产出任何件，
        #    而不是攒一个必然发不出去的 payload 再炸。
        def grasp_point_for_target(target):
            return None

    return SocketVisionSource(
        round_id=round_id,
        task_id=round_task_id,
        image_id_for_class=_identity_image_id,
        drop_point_for_box=drop_point_for_box,
        grasp_point_for_target=grasp_point_for_target,
        payload_orderer=payload_orderer,
    )

class MonitoredVisionSource:
    """包装SocketVisionSource，添加监控钩子"""

    def __init__(self, source: SocketVisionSource, monitor: MonitorBroadcaster):
        self.source = source
        self.monitor = monitor

    def set_permitted(self, permitted: bool) -> None:
        self.source.set_permitted(permitted)

    def next_if_permitted(self):
        return self.source.next_if_permitted()

    def ingest(self, data: bytes) -> None:
        """包装ingest，添加监控更新"""
        self.source.ingest(data)

        # 尝试解析并更新监控
        try:
            from electrical_control.rpi.vision_ingest import parse_batch_targets
            batch = parse_batch_targets(data)
            self.monitor.update_vision(batch)
        except Exception:
            pass  # 解析失败静默忽略（source.ingest已经处理了）

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
# 屏幕两段显示（2026-09-18 用户要求：识别到物体 → 分拣成功）
#
# 定位：**附加信息，不参与协议**。规则要求的那一帧（DISPLAY_DATA + DISPLAY_ACK、
# R-D04 显示门禁）仍然只由 _render_and_ack() 出；不要在 present() 上承载这两段。
# 触发点见主循环内 `_show_two_stage(...)` 的两处调用。
# ---------------------------------------------------------------------------
def _two_stage_info(task, names: dict[int, str]) -> TwoStageInfo:
    """ItemTaskContext + 本地名称表 → 两段显示载荷。

    校赛模式下 BATCH_TARGETS 的那个 id 字节就是货格号（颜色已折叠成 box_id），
    它同时落在 payload.class_id 与 box_id 上；颜色/形状**不在线格式里**，只能从
    本地名称就地拆（见 display.split_color_shape），拆不出显示 ``—``。
    """

    name = names.get(task.payload.class_id, "")
    color, shape = split_color_shape(name)
    return TwoStageInfo(
        target_seq=task.payload.target_seq,
        box_id=task.payload.class_id,
        name=name or None,
        color=color,
        shape=shape,
    )

def _show_two_stage(show, info: TwoStageInfo, logger: logging.Logger) -> None:
    """推一帧两段显示帧；屏幕出问题只记 ERROR，**绝不打断分拣主链**。

    与主链其它 fail-closed 门（落点表、图片、fb 格式）**故意相反**：那些门不过就是
    "本件不能做"，而这两段是附加信息，合成失败不该让 STM32 停下等一个永远不会来的
    DISPLAY_ACK。规则必须显示的那一帧仍由 _render_and_ack 的 fail-closed 路径保证。
    """

    try:
        frame = show(info)
    except Exception as exc:  # noqa: BLE001 - 屏幕问题不得升级成链路故障
        logger.error(
            "两段显示帧合成/上屏失败，链路继续: %s: %s", type(exc).__name__, exc
        )
        return
    logger.info(
        "两段显示已上屏: %dx%d target_seq=%d box_id=%s",
        frame.width, frame.height, info.target_seq, info.box_id,
    )

# ---------------------------------------------------------------------------
# 建轮次吞帧补偿（2026-09-18 实机定位）
# ---------------------------------------------------------------------------
def _should_resend_on_barrier_ready(
    scheduler: Scheduler, last_task_context: ItemTaskContext | None
) -> bool:
    """收到 BARRIER_READY 时，是否应当立刻原样重发在飞的那一帧 ITEM_TASK。

    背景（实机证据，不要凭直觉改）：
      板子开机处于 FAULT_LOCK、round_id=0。收到第一发 ITEM_TASK 时它**只用这一发
      建轮次**（ec_state_machine.c:76-86 → BEGIN_POST），然后自己跑
      POST→HOMING→PREPARE_BARRIER→WAIT_TASK，到 WAIT_TASK 才 emit BARRIER_READY
      （:127-131）。而建轮次那一发在 consume_and_emit 里**没有任何分支**
      （ec_protocol_gateway.c:66-110），tx_len 保持 0 —— **一个字节都不回**。
      同时 :79 清了 dedup、:85 直接 return，那个 identity 从未被记录，
      所以**重发同一帧会被当成"全新首件"而正常 ACK**（04:13 实机复现：
      第 1 发只回 BARRIER_READY，第 2 发同样字节回 ACK_ACCEPTED → 开始运动）。

      结论：BARRIER_READY 到达 = "刚建完轮次、那一发被启动序列吞了"，
      此时若我们还在等 MOTION_DONE，就该立刻重发，而不是干等 5 秒超时。

    只在真的有一件在飞（WAIT_MOTION_DONE + 有 task 上下文）时重发。
    板子每完成一件也会再报一次 BARRIER_READY（:203-209 → PREPARE_BARRIER），
    那时 state 已不是 WAIT_MOTION_DONE，天然不会误触发。
    """

    return last_task_context is not None and scheduler.state is SchedulerState.WAIT_MOTION_DONE

def _mm10(value: int | None) -> str:
    """0.1mm 整数 → mm 字符串（None 原样显示）。仅用于日志/诊断。

    2026-09-18 实机踩过的坑：原日志只有 target_seq/class_id/image_id，没有坐标。
    结果 X 轴被命令走到正方向机械极限顶死堵转，事后**完全看不出命令坐标是多少**，
    只能靠猜。落点和抓取点都必须打出来。
    """
    return "None" if value is None else "%.1f" % (value / 10.0)


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

    # ---- 落料策略（2026-09-17 接线）：方案A 六固定盒 / 方案B 转盘选格 ----
    # 方案判定与校验都在 load_strategy_from_config 里：
    #   有 [TurntableAngles] 节 → 方案B（落料点固定，查转盘角度）
    #   否则                   → 方案A（读 [DropPoints]，且六盒必须齐全，缺一即 SystemExit）
    # 方案A 的校验与"缺货格就拒启动"行为与接线前【完全一致】，只是搬进了工厂函数。
    if demo:
        drop_points = dict(DEMO_DROP_POINTS)
        logger.warning("--fake-link：使用 DEMO 落点表 %s（仅开发/冒烟）", drop_points)
        strategy = FixedBoxStrategy(drop_points)
        fixed_pick_point = None
    else:
        # 固定摆放模式（2026-09-18 用户裁定）：件每次放同一处 → 抓取点是常量，
        # 不需要像素→毫米标定。没有 [PickPoint] 节时返回 None，行为不变。
        fixed_pick_point = load_fixed_pick_point(args.config)
        box_map = load_box_map(args.config)
        strategy = load_strategy_from_config(args.config)
        used = sorted({b for b in box_map.values()})
        if strategy.requires_turntable_control():
            logger.info(
                "落料策略=方案B（转盘选格）：落料点固定，货格 %s 由转盘角度选格", used
            )
        else:
            logger.info("落料策略=方案A（六固定盒）：[DropPoints] 六盒已校验齐全")
            # 对应表用到的货格必须在落点表里有坐标
            no_point = [b for b in used if strategy.get_drop_point(b) is None]
            if no_point:
                raise SystemExit(f"对应表用到的货格 {no_point} 在落点表里没有坐标")
        if not box_map:
            logger.warning(
                "[BoxMap] 为空 —— 视觉侧仍会给出 box_id，但没有任何现场冻结的"
                "对应关系可校验。建议用 工具/control_panel.py 冻结后再跑"
            )

    font_path = resolve_font(args.font, logger)
    names = load_names(args.names_file, demo=demo)
    image_loader = build_image_loader(args.image_dir, demo=demo)
    frame_output = build_frame_output(
        args.frame_output, args.output_dir, logger, demo=demo
    )
    # 屏幕两段显示：与协议帧共用同一路 frame_output（fb0 时就是同一块屏）
    two_stage = TwoStageDisplay(frame_output=frame_output, font_path=font_path)
    logger.info("两段显示字体: %s", two_stage.font_path or "PIL 内置（中文会是方块）")

    # ---- 启动监控模块 ----
    monitor = MonitorBroadcaster(port=MONITOR_PORT)
    monitor.start(logger)

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
    if demo:
        scheduler.load_source(
            build_placeholder_source(round_id=round_id, round_task_id=round_task_id, demo=demo)
        )
    else:
        payload_orderer = None
        if args.pick_strategy == "order":
            from electrical_control.pick_strategy.chain_adapter import (
                payload_orderer_from_ini,
            )
            payload_orderer = payload_orderer_from_ini(args.pick_strategy_config)
            if payload_orderer is None:
                logger.warning("夹取策略：构造失败，本次退回默认排序")
            else:
                logger.info("夹取策略：已启用 order 模式（只改顺序、不丢件），配置=%s",
                            args.pick_strategy_config)
        source = build_socket_source(
            round_id=round_id,
            round_task_id=round_task_id,
            drop_point_for_box=strategy.get_drop_point,
            calibration_config=args.calibration_config,
            fixed_pick_point=fixed_pick_point,
            payload_orderer=payload_orderer,
        )
        # 包装视觉源，添加监控钩子
        monitored_source = MonitoredVisionSource(source, monitor)
        scheduler.load_source(monitored_source)
        stop_event = threading.Event()
        listener = threading.Thread(
            target=vision_listener,
            args=(monitored_source,),  # 使用包装后的source
            kwargs={"stop_event": stop_event},
            name="vision-listener",
            daemon=True,
        )
        listener.start()
        logger.info("视觉监听线程已启动: 0.0.0.0:8765")

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
    # 段2 的待显示载荷：MOTION_DONE 时记下，等规则帧出完再落屏（见该分支注释）
    success_info: TwoStageInfo | None = None
    # 超时重传状态：记录上次派发/重传时间和任务上下文
    last_task_sent_at = 0.0
    last_task_context = None
    task_timeout_s = 5.0  # 2026-09-21 回落：NACK 已改成立即重试，超时只用于真静默；恢复越快越好
    # 🔴 2026-09-21 新增：板子明确拒收（NACK）时的重试退避。
    #   实机证据（R3/R4 两轮）：每件收 DISPLAY_ACK 后链立刻派下一件，而板子还没收尾完、
    #   没进 WAIT_TASK ⇒ 回 NACK_ACK_NOT_APPLICABLE + NACK_SINGLE_TASK_ONLY。
    #   旧代码把 NACK 落到最后的 else 分支**只打日志、不重试** ⇒ 只能干等满超时
    #   ⇒ **每件白拖 ~8 秒（实测 21~22s/件）**。
    nack_retry_backoff_s = 0.3

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
            last_task_sent_at = time.monotonic()
            last_task_context = task
            success_info = None  # 新的一件：清掉上一件遗留的「分拣成功」载荷

            # 更新监控：电控指令
            monitor.update_item_task(task)

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
                "ITEM_TASK sent: target_seq=%d class_id=%d image_id=%d "
                "落点=(%s,%s)mm 抓取点=(%s,%s)mm",
                task.payload.target_seq, task.payload.class_id, task.payload.image_id,
                _mm10(task.payload.x_position), _mm10(task.payload.y_position),
                _mm10(task.payload.pick_x_position), _mm10(task.payload.pick_y_position),
            )
            # 段1：识别到待分拣物体 → 立刻把该物体信息显示出来（在 ITEM_TASK 之后，
            # 不占用发令时间）。失败只记 ERROR，不停链（见 _show_two_stage）。
            _show_two_stage(
                two_stage.show_recognized, _two_stage_info(task, names), logger
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
            if demo:
                logger.info("任务源已耗尽（demo 队列），本轮结束")
                break
            # 真实模式：SocketVisionSource 是动态源，暂无任务时继续等待新物体。

        # 2) 超时检查：若有活动任务且超时，重传 ITEM_TASK
        if last_task_context is not None and (time.monotonic() - last_task_sent_at) > task_timeout_s:
            logger.warning(
                "ITEM_TASK 超时 %.1fs 无应答，重传 frame_seq=%d",
                task_timeout_s,
                last_task_context.frame_seq,
            )
            raw_resend = outbound.resend_item_task(last_task_context)
            last_task_sent_at = time.monotonic()  # 更新时间，避免每轮都重传
            cl.record(
                TASK,
                now=time.monotonic(),
                round_id=last_task_context.round_id,
                task_id=last_task_context.task_id,
                frame_seq=last_task_context.frame_seq,
                target_seq=last_task_context.payload.target_seq,
                detail=f"ITEM_TASK 重传 ({len(raw_resend)}B), timeout={task_timeout_s}s",
            )

        # 3) 轮询入站：整帧交给网关分发
        frame = link.receive()
        if frame is None:
            if time.monotonic() - last_status > 10.0:
                logger.info("空闲: state=%s success=%d", scheduler.state.name, scheduler.success_count)
                last_status = time.monotonic()
            time.sleep(0.005)  # 轮询节流（压缩空闲周期，降低视觉→串口转发延迟）
            continue

        outcome = gateway.feed_frame(frame)
        event = outcome.event

        if event == "MOTION_DONE":
            # gateway 已校验 task_id 并调用 scheduler.accept_motion_done（→ WAIT_ITEM_RESULT）
            logger.info("inbound: MOTION_DONE accepted")
            # 重置超时计时：已收到 MOTION_DONE，等待 ITEM_RESULT
            last_task_sent_at = time.monotonic()
            # 段2 的触发点（2026-09-18 用户拍板：以 STM32 报**动作完成**为准，不等转盘到位）。
            # 这里只**记下**载荷、不画：MOTION_DONE 与 ITEM_RESULT 通常几毫秒内先后到达，
            # 此刻画出的「分拣成功」会被紧接着的规则帧盖掉（肉眼看不到）。
            # 所以改在规则帧（_render_and_ack）之后落屏 → 一直留在屏上，直到下一件的段1。
            # 结果码要到 ITEM_RESULT 才知道，是否真失败也在那里判。
            current = scheduler.current_task
            success_info = (
                _two_stage_info(current, names) if current is not None else None
            )
        elif event == "ITEM_RESULT":
            # gateway 已解析 payload 并调用 scheduler.accept_item_result（→ WAIT_RENDER）
            logger.info("inbound: ITEM_RESULT accepted")
            # 清除超时状态：任务完成，进入渲染阶段（无需超时重传）
            last_task_context = None
            # accept_render_receipt 会清空 display_model，须在渲染之前读结果码
            display_content = scheduler.display_model
            is_success = (
                display_content is not None and display_content.result_code == 0
            )

            # 更新监控：执行结果（从outcome获取payload信息）
            # gateway已经解析了payload，我们需要从decode_item_result_payload重新解析
            from electrical_control.protocol import decode_item_result_payload
            try:
                # 从原始frame中提取payload
                decoded_frame = gateway._last_inbound_frame if hasattr(gateway, '_last_inbound_frame') else None
                if decoded_frame and decoded_frame.payload:
                    result_payload = decode_item_result_payload(decoded_frame.payload)
                    monitor.update_item_result(
                        result_payload.target_seq,
                        result_payload.result_code,
                        result_payload.basis
                    )
            except Exception as e:
                logger.debug(f"[MONITOR] 解析ITEM_RESULT失败: {e}")

            _render_and_ack(scheduler, outbound, names, image_loader,
                            frame_output, font_path, cl, logger)
            # 段2：动作已完成（MOTION_DONE）且结果码 SUCCESS → 规则帧之后再落屏，
            # 于是「分拣成功」留在屏上直到下一件的段1；失败件不显示成功（见上方触发点注释）。
            if success_info is not None:
                if is_success:
                    _show_two_stage(two_stage.show_success, success_info, logger)
                else:
                    logger.warning(
                        "结果码非 SUCCESS（target_seq=%d）：不显示「分拣成功」",
                        success_info.target_seq,
                    )
            success_info = None
        elif event == "BARRIER_READY":
            logger.info("inbound: BARRIER_READY（STM32 就绪上报）")
            # 建轮次那一发被板子的启动序列吞掉且零应答（见该函数注释）：
            # 在飞时立刻原样重发，把"每件白等 5 秒"消掉。
            if _should_resend_on_barrier_ready(scheduler, last_task_context):
                raw_resend = outbound.resend_item_task(last_task_context)
                last_task_sent_at = time.monotonic()
                logger.warning(
                    "BARRIER_READY = 建轮次那一发 ITEM_TASK 已被启动序列吞掉，立即重发"
                    "（不再等 %.1fs 超时）: frame_seq=%d (%dB)",
                    task_timeout_s,
                    last_task_context.frame_seq,
                    len(raw_resend),
                )
                cl.record(
                    TASK,
                    now=time.monotonic(),
                    round_id=last_task_context.round_id,
                    task_id=last_task_context.task_id,
                    frame_seq=last_task_context.frame_seq,
                    target_seq=last_task_context.payload.target_seq,
                    detail=f"建轮次后立即重发 ITEM_TASK ({len(raw_resend)}B)",
                )
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
        elif isinstance(event, str) and event.startswith("NACK"):
            # 🔴 2026-09-21：板子明确拒收在飞的那一帧（典型 NACK_SINGLE_TASK_ONLY）。
            # 立刻带小退避重发，不再干等超时。
            cl.record(TASK, now=time.monotonic(), detail="inbound %s（立即重试）" % event)
            logger.warning("inbound %s：板子拒收本帧，%.1fs 后立即重发", event, nack_retry_backoff_s)
            if last_task_context is not None:
                time.sleep(nack_retry_backoff_s)
                try:
                    raw_resend = outbound.resend_item_task(last_task_context)
                except Exception:
                    logger.warning("NACK 后重发失败（保留在飞状态，等超时重传）", exc_info=True)
                else:
                    last_task_sent_at = time.monotonic()
                    cl.record(TASK, now=time.monotonic(),
                              detail="NACK(%s) 后立即重发 (%dB)" % (event, len(raw_resend)))
            else:
                logger.warning("收到 %s 但没有在飞的件：忽略", event)
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
