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
          ACK_ACCEPTED → 板子已受理在飞件 ⇒ **清 last_task_context，停该件重传**（A5，2026-09-22）
          NACK_*       → 按原因码判别：可重试的带退避立刻重发，必然再被拒的 fail-closed 收场
                         （事件名由 gateway._handle_ack_nack 生成：f"{kind}_{reason_name}"，
                           见 electrical_control/rpi/gateway.py:193-228；**不是** IGNORED）
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
from electrical_control.rpi.turntable import TurntableError
from electrical_control.rpi.turntable_guard import build_turn_guard
# 2026-11-07（S3 骨架）：挡板巡检三态 + D7 动作映射。模块默认 off，off 时一行都不执行。
from electrical_control.rpi.barrier_check import (
    BarrierCheckError,
    BarrierState,
    unknown_action,
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
DEMO_NAMES = {
    1: "演示件1", 2: "红方柱", 3: "演示件3", 4: "蓝圆柱",
    5: "演示件5", 6: "演示件6",
}  # class_id -> 货物名称（模拟本地 TF 卡名称表；1..6 供 --demo-items 6 用）
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
        self.latest_place_check: dict | None = None
        self.place_runtime = None          # 2026-11-01：落料位复看运行时（可空）

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
        # 2026-11-01：落料完成（ITEM_RESULT 成功）→ 用副相机在落料位复看
        rt = self.place_runtime
        if rt is not None and rt.enabled():
            code = None
            task = self.latest_item_task or {}
            if task.get('target_seq') == target_seq:
                code = task.get('class_id')
            box_id = None
            batch = self.latest_vision_batch or {}
            for t in (batch.get('targets') or []):
                if t.get('target_seq') == target_seq:
                    box_id = t.get('box_id')
                    break
            if code is not None:
                try:
                    self.latest_place_check = rt.on_item_result(
                        target_seq=target_seq, class_id=int(code),
                        box_id=box_id, result_code=int(result_code))
                except Exception:
                    self.latest_place_check = {"verdict": "UNKNOWN",
                                               "reason": "复看运行时异常"}
        self._send_status()

    def _send_status(self) -> None:
        """发送汇总状态"""
        status = {
            'timestamp': time.time(),
            'vision': self.latest_vision_batch,
            'item_task': self.latest_item_task,
            'item_result': self.latest_item_result,
            'place_check': getattr(self, 'latest_place_check', None),
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
    # 2026-10-23：统一剥行内注释。configparser 默认不剥 ⇒ 值后写 `# 注释`
    # 会让该值解析失败/被静默跳过，而错误信息看不出真因。已核对现行
    # sorting_config.ini 的所有值里都没有 `#`，此参数安全。
    # ⚠️ 与 pixel_to_device.py:210、drop_strategy.py 保持一致。
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#",))
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


def config_has_section(path: str | Path, section: str) -> bool:
    """只探测某一节是否存在（不解析内容、**绝不抛异常**）。

    用途：`--fake-link` 主机冒烟时决定"按方案C 装配"还是"用 DEMO 落点表"。

    ⚠️ 必须容错：这只是一次**探测**，任何解析失败都应当作"没有这一节"返回 ——
       否则一个带 BOM 或格式错误的 ini 会把整条启动流程炸掉
       （2026-09-21 主机冒烟实测：`Set-Content -Encoding UTF8` 写出的 BOM
        让 configparser 抛 `File contains no section headers`）。
       `utf-8-sig` 用来吃掉可能存在的 BOM。
    """
    p = Path(path)
    if not p.exists():
        return False
    # 2026-10-23：统一剥行内注释。configparser 默认不剥 ⇒ 值后写 `# 注释`
    # 会让该值解析失败/被静默跳过，而错误信息看不出真因。已核对现行
    # sorting_config.ini 的所有值里都没有 `#`，此参数安全。
    # ⚠️ 与 pixel_to_device.py:210、drop_strategy.py 保持一致。
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#",))
    try:
        cfg.read(p, encoding="utf-8-sig")
    except (configparser.Error, UnicodeDecodeError, OSError):
        return False
    return cfg.has_section(section)


def load_drop_points(path: str | Path) -> dict[int, tuple[int, int]]:
    """从 sorting_config.ini 的 [DropPoints] 读六盒落点。

    文件里单位是 **mm**（`工具/control_panel.py` 按 mm 写），ITEM_TASK 要
    **0.1mm**，这里换算。读不到条目就返回空表 —— 调用方 fail-closed，
    绝不猜坐标：猜错 = 货落错盒，直接违反“形状颜色一致的放同一个盒”。
    """
    p = Path(path)
    if not p.exists():
        return {}
    # 2026-10-23：统一剥行内注释。configparser 默认不剥 ⇒ 值后写 `# 注释`
    # 会让该值解析失败/被静默跳过，而错误信息看不出真因。已核对现行
    # sorting_config.ini 的所有值里都没有 `#`，此参数安全。
    # ⚠️ 与 pixel_to_device.py:210、drop_strategy.py 保持一致。
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#",))
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
    # 2026-10-23：统一剥行内注释。configparser 默认不剥 ⇒ 值后写 `# 注释`
    # 会让该值解析失败/被静默跳过，而错误信息看不出真因。已核对现行
    # sorting_config.ini 的所有值里都没有 `#`，此参数安全。
    # ⚠️ 与 pixel_to_device.py:210、drop_strategy.py 保持一致。
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#",))
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
        help="启动时开始一轮 verified new round；真实模式会先要求操作员输入 HOME，"
        "确认滑台已在负向最里角（板子无绝对位置，无法自动检测）",
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
        "--demo-items", type=int, default=2,
        help="--fake-link 演示件数（默认 2；=6 时喂 code=1..6，用于验证动态分配 1→6 与转盘逐格）",
    )
    parser.add_argument(
        "--barrier-check", choices=("off", "observe", "stop"),
        default=_env("BARRIER_CHECK", "off"),
        help="挡板巡检（S3）：off=关闭（默认）/ observe=只记录 / stop=发现异常即停链",
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
        help="夹取策略：off=按现有贪心最近邻取件（**默认，与接入前逐字节一致**）；"
        "order=用 pick_strategy 的「离托盘无壁边最近」规则选件（α：只改顺序、不丢件）。"
        "配套配置 --pick-strategy-config",
    )
    parser.add_argument(
        "--pick-strategy-config",
        default=_env("PICK_STRATEGY_CONFIG", "/home/pi/电控/deploy/pick_strategy.ini"),
        help="--pick-strategy=order 时使用的策略配置文件（缺失或解析失败 ⇒ 自动退回 off）",
    )
    parser.add_argument(
        "--verify-place", choices=("off", "observe", "correct"),
        default=_env("VERIFY_PLACE", "off"),
        help="落料位复看（副相机 + Pi 本地 HSV 判色）：off=不看（默认）；"
             "observe=只看只统计；correct=不符时纠正货格分配台账",
    )
    parser.add_argument(
        "--place-eye-config", default=_env("PLACE_EYE_CONFIG", None),
        help="[PlaceEye] 所在 ini（缺省=与 --config 同一个 sorting_config.ini）",
    )
    parser.add_argument(
        "--slot-mode", choices=("static", "dynamic"), default=_env("SLOT_MODE", "static"),
        help="货格分配：static=用 [BoxMap] 静态表（默认，行为不变）；"
             "dynamic=运行时按 code 分配货格（同 code 复用同格、同侧优先少换挡）",
    )
    parser.add_argument(
        "--slot-journal", default=_env("SLOT_JOURNAL", "/home/pi/slot_alloc.json"),
        help="dynamic 模式的分配台账路径（按 round_id 持久化，重启不丢）",
    )
    parser.add_argument(
        "--anchor",
        choices=("last_drop", "fixed"),
        default=_env("SORT_ANCHOR", "last_drop"),
        help="排序锚点（审核 D1）：last_drop=用『上一次落料点』（默认，修掉固定 (0,0)）；"
             "fixed=沿用构造时的固定锚点（一键回退用）。",
    )
    parser.add_argument(
        "--order-mode",
        choices=("auto", "legacy", "group", "difficulty", "open_edge", "five_key",
                 "weighted"),
        default=_env("ORDER_MODE", "auto"),
        help="夹取策略排序口径（仅 --pick-strategy=order 生效）。"
             "auto=用配置 [Strategy] order_mode（缺省 legacy=不排序）；"
             "group=分组→待定→难度→行扫描（现状默认）；"
             "difficulty=只按难度分层；open_edge=离无壁边最近；"
             "five_key=停稳→待定→难度→隔离度→落点距离（2026-11-01 新增）；"
             "weighted=加权评分：前端/夹取/路线/隔离度（2026-11-02 新增，权重见 [Strategy]）；"
             "legacy=不排序（原顺序）。",
    )
    parser.add_argument(
        "--settle-frames", type=int, default=_env_int("SETTLE_FRAMES", 3),
        help="five_key 模式：连续多少帧位置不变才算『停稳』（默认 3）",
    )
    parser.add_argument(
        "--settle-shift-mm", type=float, default=float(_env_int("SETTLE_SHIFT_MM", 4)),
        help="five_key 模式：停稳判据的中心位移阈值 mm（默认 4）",
    )
    parser.add_argument(
        "--first-dispatch-settle",
        type=int,
        default=_env_int("FIRST_DISPATCH_SETTLE", 3),
        help="**首件稳定门**（2026-09-22 用户裁决「为顺序牺牲一点起轮时间」）："
        "本轮第一件必须等台面【连续这么多帧】签名稳定才放行，避免"
        "「链在视觉起来后 ~167ms 就派第一件、那一帧件不全 ⇒ 排序器无从比较」"
        "导致先夹中间那件。**0 = 关闭，回到本改动前的行为**。"
        "派过一件之后永久放行，不影响后续件。",
    )
    parser.add_argument(
        "--first-dispatch-max-wait",
        type=float,
        default=float(_env_int("FIRST_DISPATCH_MAX_WAIT_MS", 500)) / 1000.0,
        help="首件稳定门的等待上限（秒）。**2026-09-22 由 2.0 收到 0.5**："
        "实测 5000Hz 下第一件本来就要 15.15s（已压线），上限 2.0s 会把第一件推过 15s 红线。"
        "0.5s = 帧快时稳定门照常生效、帧慢时最多只吃 0.5s 并记 WARNING。"
        "超时按当前帧放行（无上限时「操作员还在摆件」会让链在起轮处无限等，"
        "而 15s 红线从起轮算起，那比顺序错严重得多）。",
    )
    parser.add_argument(
        "--round-idle-timeout",
        type=float,
        default=float(_env_int("ROUND_IDLE_TIMEOUT_MS", 15000)) / 1000.0,
        help="**N2-a 空闲收场**：READY 且【当前没有运动在飞】时，连续这么多秒没有可派发的"
        "新件 ⇒ 判本轮结束、干净收场（打汇总 → 退出 0）。"
        "取 15.0 与赛规「15 秒没有动作或没有显示本次分拣信息，本轮结束」同值；"
        "**这一段里没有运动**，所以不会误判件周期。**0 = 关闭**（回到旧行为：无限等）。",
    )
    parser.add_argument(
        "--inflight-timeout",
        type=float,
        # 🔴 2026-09-22 夜修：20.0 → 35.0。
        # 实测（round-R8-230512）：派发 23:05:13.3 → 我的 20.0s 钟在 23:05:33.3 收场，
        # 而板子在同一轮把 12 步程序【完整跑完】（MOVES 34→40、PROGRESS=12、STATE=DONE、
        # FAULTS=0、孤立轴保护零触发）⇒ 那一件跑得比平时慢（≈20 s），
        # 钟在它完成前 0~1 秒就判了"板子静默"，于是整轮白丢（链 success=0，机器却把件送对了）。
        # 实测单件体量：件间 15 s、单件 MOTION_DONE 13~16 s，最慢观察到 ≈20 s。
        # 35.0 = 最慢件 + 启动序列/首件整定/两次重传的余量；运动期间机器一直在动，
        # 赛规 R-R04「超过 15 秒装置没有动作」不成立 ⇒ 等久一点不违规。
        default=float(_env_int("INFLIGHT_TIMEOUT_MS", 35000)) / 1000.0,
        help="**N2-b 在飞收场**：发了 ITEM_TASK 之后超过这么多秒仍没收到 MOTION_DONE"
        " ⇒ 判板子静默、记 FAULT、干净收场（不再无限重传，退出 1）。"
        "🔴 **必须大于最坏单件时长**：实测第一件 发令→MOTION_DONE = **15.154s**"
        "（2026-09-21 18:55 轮）⇒ 取 20.0s 留余量。"
        "⚠️ **不要用 15.0 当这个阈值** —— 那会在**正常**的第一件上误判。**0 = 关闭**。",
    )
    return parser.parse_args(argv)


# 🔴 2026-09-22 修复（F3）：NACK 原因码分两类。
#   可重试 = 板子"还没准备好收这一件"（还在收尾上一件 / 还没进到能收的状态），
#            等它一下再发同一帧就能成功 —— 这是 2026-09-21 那条补丁要救的场景，
#            实测每件都会遇到（R3/R4 轮证据），**必须保留**。
#   不可重试 = 重发同一字节必然再被拒（轮次不符 / 顺序不符 / 通用拒收 / 未知码），
#            旧代码在这里会变成 0.3s 一次、约 3 次/秒的**无限循环**，而且
#            sleep 阻塞主循环、每轮还刷新 last_task_sent_at 把 5s 超时架空
#            ⇒ 整轮永久卡死、且永远不补发真正需要重发的 DISPLAY_ACK。
_NACK_RETRYABLE = {
    "NACK_SINGLE_TASK_ONLY",     # 0x12：板子还在处理上一件
    "NACK_ACK_NOT_APPLICABLE",   # 0x13：板子还没进到能收 DISPLAY_ACK 的状态
}


def _nack_is_retryable(event: str) -> bool:
    """True = 原样重发值得试；False = 重发必然再被拒（调用方应 fail-closed 收场）。

    未知原因码（``NACK_UNKNOWN(0xNN)``）一律返回 False —— 不认识的拒绝不许进重试循环。
    """
    return event in _NACK_RETRYABLE


def _round_close_reason(
    *,
    now: float,
    inflight_since: float | None,
    idle_since: float,
    inflight_timeout_s: float,
    round_idle_timeout_s: float,
) -> str | None:
    """两支钟的收场判据（纯函数；自检见 deploy/selftest_round_close.py）。

    返回 ``"inflight"`` / ``"idle"`` / ``None``。

    * **在飞钟优先且在飞时独占**：只要还有运动在飞（``inflight_since is not None``），
      就**只看**"板子静默"这一条，空闲钟完全不参与 —— 否则一件正常的 12~15s 件
      会被空闲钟当成"台面没件了"而误判本轮结束（那是把好轮判死）。
    * 阈值 ``<= 0`` = 关闭该支钟（回到"无限等 / 无限重传"的旧行为）。
    * 边界取 ``>=``：正好等于阈值即判到点（与固件 15s 窗的 ``>=`` 口径一致）。
    """
    if inflight_since is not None:
        if (inflight_timeout_s > 0) and ((now - inflight_since) >= inflight_timeout_s):
            return "inflight"
        return None
    if (round_idle_timeout_s > 0) and ((now - idle_since) >= round_idle_timeout_s):
        return "idle"
    return None


def require_home_confirmation(
    args: argparse.Namespace,
    *,
    input_fn=input,
    output=sys.stderr,
) -> None:
    """真实 ``--start-round`` 的人工 HOME 门禁；在串口/视觉初始化前调用。

    X/Y 无编码器且不执行寻零，软件无法读取绝对位置。此门禁只能防止“忘记确认”，
    不能证明操作员确实把滑台推到了 HOME；输入必须精确为 ``HOME``，EOF/非交互
    启动也一律拒绝。``--fake-link`` 是主机逻辑测试，不触碰机构，因此跳过。
    """

    if not args.start_round or args.fake_link:
        return

    banner = "\n".join((
        "",
        "!" * 72,
        "!!! 启动拦截：板子无法自动判断 XY 是否位于 HOME !!!",
        "期望起点：X=-95.0mm, Y=-97.5mm（X/Y 负方向最里角，均顶住）",
        "判据：上电/跑链路前已人工把 X、Y 推到各自负向机械极限。",
        "未确认时绝不能发送 --start-round；错误起点会令第一段增量运动整体偏移，",
        "可能顶死堵转并使开环坐标永久失准。",
        "!" * 72,
    ))
    print(banner, file=output, flush=True)
    try:
        answer = input_fn("确认滑台已在 HOME 后输入 HOME（其他输入均退出）：")
    except (EOFError, OSError) as exc:
        raise SystemExit(
            "HOME 未确认：当前启动环境不可交互。移除 --start-round 保持待命，"
            "或在现场终端人工确认后启动。"
        ) from exc
    if answer.strip() != "HOME":
        raise SystemExit("HOME 未确认：拒绝 --start-round，未打开串口、未启动视觉线程。")

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

def build_placeholder_source(*, round_id: str, round_task_id: int, demo: bool,
                            items: int = 2) -> FakeTaskSource:
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
        if items > 2:
            # 2026-11-07（S2）：多件 demo —— 验证「动态分配 1→6 + 转盘逐格下发」，
            # code 用 1..items，货格号也先用 1..items（动态分配会把 code 映射成格号）。
            _targets = tuple(
                VisionTarget(seq, seq, pixel_x=100 + 40 * seq, pixel_y=100 + 30 * seq,
                             box_id=seq)
                for seq in range(1, int(items) + 1)
            )
            batch = BatchTargets(round_task_id, _targets)
            queue = build_item_task_queue(
                batch,
                image_id_for_class=lambda class_id: int(class_id),
                drop_point_for_box=lambda box_id: (100 + 10 * int(box_id),
                                                   200 + 10 * int(box_id)),
                grasp_point_for_target=lambda target: (
                    -300 + 20 * int(target.target_seq), 150),
            )
        else:
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
                grasp_point_for_target=lambda target: DEMO_GRASP_POINTS.get(
                    target.target_seq),
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
    # 夹取策略（--pick-strategy=order）注入的「选哪一件」排序器；默认 None ⇒ 行为不变。
    payload_orderer: Callable[[tuple[object, ...]], tuple[object, ...]] | None = None,
    current_position_provider: Callable[[], tuple[int, int] | None] | None = None,
    box_id_resolver: Callable[[int], int | None] | None = None,
    class_id_filter: Callable[[int], bool] | None = None,
    # 首件稳定门（见 SocketVisionSource 的注释）。两个默认值 = **关闭**，
    # 由 run_chain 的 --first-dispatch-settle 传下来（默认 3 帧）。
    first_dispatch_settle_frames: int = 0,
    first_dispatch_max_wait_s: float = 2.0,
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
            "物体高度 %d 类，pixel_to_device 后工具偏移=(%.1f,%.1f)mm）",
            converter.config_path,
            converter.x_limits[0], converter.x_limits[1],
            converter.y_limits[0], converter.y_limits[1],
            len(converter.object_heights),
            converter.tool_offset_mm[0], converter.tool_offset_mm[1],
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
        current_position_provider=current_position_provider,
        box_id_resolver=box_id_resolver,
        class_id_filter=class_id_filter,
        first_dispatch_settle_frames=first_dispatch_settle_frames,
        first_dispatch_max_wait_s=first_dispatch_max_wait_s,
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
    seq_no: int | None = None,  # 本件序号（2026-09-22：与两段显示同源 = done_items）
    completed_rows: list | None = None,  # 本轮已完成件 [(序号,名称,image_id,累计数)]（R-D03 表格）
) -> None:
    # 🔴 2026-09-22：表格帧渲染（逐件累加，R-D03）；import 放函数内，避免顶层依赖变化
    from electrical_control.rpi.display_table import compose_table_frame

    def _null_frame_output(_frame) -> None:
        """空 sink：面板帧不再落屏（屏上改画表格，见本函数末尾）。"""
        return None
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
        frame_output=_null_frame_output,  # 🔴 2026-09-22：面板帧不再落屏（改画表格，见下）
        font_path=font_path,
        task=task,  # 构造时注入活动任务，complete() 才能重建正确 DisplayContent/CRC
        seq_no=seq_no,  # 本件序号（修正合规帧「第 N 件」错一位；None ⇒ 保持旧行为）
    )
    pending = renderer.present(view)  # 只算 receipt/CRC（帧输出是空 sink，不写屏）
    receipt = pending.complete()      # PendingRender.complete() → RenderReceipt（含 content_crc32）

    # 🔴 2026-09-22 改（R-D03，用户确认版式）：屏上落的是【逐件累加表格】
    #     · 每完成一件**追加一行**（序号 / 货物名称 / 图片 / 分拣成功总数量，末列为该件完成时的累计值）
    #     · 最多显示最近 6 行；最新一行高亮
    #     · 图片取不到 ⇒ compose_table_frame 抛 ValueError ⇒ 本帧不落屏（fail-closed，不留半张表）
    #    wire 不受影响：DisplayContent / CRC / DISPLAY_ACK 全部沿用上面 renderer 产出的 receipt ✓
    if completed_rows is not None:
        completed_rows.append((
            seq_no if seq_no is not None else int(view.success_count),
            view.name,
            int(view.image_id),
            int(view.success_count),
        ))
        frame_output(compose_table_frame(
            completed_rows,
            image_loader=image_loader,
            font_path=font_path,
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
            max_rows=6,
        ))

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
def _two_stage_info(
    task, names: dict[int, str], *, seq_no: int | None = None
) -> TwoStageInfo:
    """ItemTaskContext + 本地名称表 → 两段显示载荷。

    校赛模式下 BATCH_TARGETS 的那个 id 字节就是货格号（颜色已折叠成 box_id），
    它同时落在 payload.class_id 与 box_id 上；颜色/形状**不在线格式里**，只能从
    本地名称就地拆（见 display.split_color_shape），拆不出显示 ``—``。

    ``seq_no`` = 屏上「序号」= **本轮第几件**。调用方传 ``done_items``（每派发一件 +1，
    单调、不重复）。⚠️ **不能用 target_seq**（视觉每帧内的序号，会重复回退），
    ⚠️ 也不要用 ``scheduler.success_count``（只在成功时递增，失败件那号会被下一件重复）。
    两个调用点都传同一个 ``done_items`` ⇒ 同一件的段1/段2 显示同一个序号。
    """

    name = names.get(task.payload.class_id, "")
    color, shape = split_color_shape(name)
    return TwoStageInfo(
        target_seq=task.payload.target_seq,
        box_id=task.payload.class_id,
        name=name or None,
        color=color,
        shape=shape,
        seq_no=seq_no,
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
        # seq_no = 屏上实际显示的「序号」；target_seq 只作追踪（它会重复回退，别拿它当件号）。
        "两段显示已上屏: %dx%d 序号=%s target_seq=%d box_id=%s",
        frame.width, frame.height,
        "未接线" if info.seq_no is None else info.seq_no,
        info.target_seq, info.box_id,
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

def _should_stop_resend_on_ack_accept(
    last_task_context: ItemTaskContext | None, ack_task_id: int | None
) -> bool:
    """收到 ACK_ACCEPTED 时，是否应当**停掉该件的超时重传**（清 last_task_context）。

    背景（A5，2026-09-22 定位，别再改回去）：
      板子明确受理了在飞的那一帧之后，链路仍会每 task_timeout_s(5s) 重传一次
      —— 因为收到 MOTION_DONE 只重置了 last_task_sent_at，**没有清
      last_task_context**，而在飞判据（:1450 附近）只看"有上下文 + 超时"。
      实机后果：一轮 23 次无谓重传。

    ⚠️ 为什么不能"只看 ACK 类型就清"：必须核对身份。
      线上 task_id 字段的语义 = **本轮任务号**（Pi 侧 outbound.py:74-78 强制
      task.task_id == config.round_task_id；板子侧 ec_protocol_gateway.c:30
      用同一字段承载 sm.round_id，并在 :223 校验相等才 ACK）。
      ⇒ 在本轮内它是**常量**，所以这条只能挡住"别的轮次的迟到 ACK"，
        挡不住"同轮内别的件的 ACK"。若日后要更强的判据，用 ACK 载荷里的
        target_seq（gateway 目前只把它记进 CentralLog，没有放进事件名）。

    ⚠️ 清了之后**不会永久吊死**：N2-a 在飞钟 (inflight_since / 35s) 仍在走，
      板子受理后不发 MOTION_DONE ⇒ 35s 后照旧 fail-closed 收场。
    """
    if last_task_context is None:
        return False
    if ack_task_id is None:
        # 🔴 2026-09-22：取不到 ACK 的身份时**不清**（fail-closed）。
        #   为什么写这一条：本函数的调用点曾把 `link.receive()` 的**原始 bytes**
        #   当成解析后的帧传进来（`frame.task_id`）⇒ AttributeError 把整条链带走
        #   （实机 round-R8-075620）。现在调用方取不到就传 None，这里也必须能接住。
        return False
    return ack_task_id == last_task_context.task_id

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
def _wire_position_turntable(strategy, config_path, *, demo: bool, logger):
    """装配方案B 的转盘：位置域 `Turntable` + 读回到位守卫（2026-11-07）。

    位置表来自 `[TurntableAngles]` 的 `pos:NNNN`（drop_strategy 已解析，混用/缺格已
    fail-closed）。`[Turntable]` 段是**可选**的现场覆盖（settle_s / 到位容差 / 超时），
    缺省用 `turntable.py` 里 2026-10-17 实测的默认值。
    """
    from electrical_control.rpi.turntable import (
        FakeBackend,
        Turntable,
        TurntableConfig,
        make_backend,
    )
    from electrical_control.rpi.turntable_position_guard import (
        ArrivalConfig,
        PositionTurnGuard,
    )

    angles = dict(getattr(strategy, "angle_table", {}) or {})
    positions = dict(getattr(strategy, "pos_table", {}) or {})
    if not positions:
        logger.warning(
            "方案B 用的是角度表（旧 270° 口径）：360° 分度请把 [TurntableAngles] "
            "改成 pos:NNNN 写法（角度表缺绝对基准，±180° 以上会越界）"
        )

    # 到位超时默认值必须跟舵机移动时间联动（2026-11-07 复核建议 2）：
    # 现默认 move_ms=1500 ⇒ max(2.5, 1.5+1.2)=2.7s；现场把 TURNTABLE_MOVE_MS 调大
    # （如慢转 3000ms）时不会误锁。`[Turntable] arrive_timeout_s` 一旦显式给出则以它为准。
    move_ms = 1500
    try:
        move_ms = int(os.environ.get("TURNTABLE_MOVE_MS", "1500"))
    except ValueError:
        logger.warning("TURNTABLE_MOVE_MS 非法：按默认 1500ms 计算到位超时")
    settle_s, tol = 0.6, 20
    timeout_s = max(2.5, move_ms / 1000.0 + 1.2)
    try:
        cp = configparser.ConfigParser(inline_comment_prefixes=("#",))
        cp.read(config_path, encoding="utf-8-sig")   # 容忍 Windows BOM
        if cp.has_section("Turntable"):
            def _num(key: str, default, cast):
                try:
                    return cast(cp.get("Turntable", key))
                except (configparser.Error, ValueError):
                    logger.warning("[Turntable] %s 解析失败，用默认 %s", key, default)
                    return default

            settle_s = float(_num("settle_s", settle_s, float))
            tol = int(_num("arrive_tolerance_counts", tol, int))
            if cp.has_option("Turntable", "arrive_timeout_s"):
                timeout_s = float(_num("arrive_timeout_s", timeout_s, float))
            else:
                logger.info(
                    "[Turntable] 未配 arrive_timeout_s：按 move_ms=%d 推导 = %.1fs",
                    move_ms, timeout_s)
    except Exception:  # noqa: BLE001 - 配置读失败不应阻断装配（默认值可用）
        logger.warning("读 [Turntable] 段失败：按默认值装配", exc_info=True)

    config = TurntableConfig(
        zero_pulse_us=1500,
        us_per_degree=655.0 / 90.0,
        angle_sign=-1,
        angle_table=angles,
        pos_table=positions,
        settle_s=settle_s,
    )
    backend = FakeBackend() if demo else make_backend()
    if demo:
        # 2026-11-07 复核建议 3：FakeBackend 的 read_pos 会回显刚写入的目标，
        # 冒烟里的"到位"是构造出来的 —— 只证明时序/接线逻辑，不证明真实串口读回。
        logger.warning(
            "方案B 冒烟用的是 FakeBackend：read_pos 回显目标 ⇒ **到位是构造的**，"
            "不证明真实串口读回；真机验收必须另做（M1–M3 回填后单件真跑）。"
        )
    turntable = Turntable(config, backend)
    guard = PositionTurnGuard(
        turntable, ArrivalConfig(tolerance_counts=tol, timeout_s=timeout_s)
    )
    logger.info(
        "落料策略=方案B（转盘选格·位置域）：%d 格，容差 ±%d counts，超时 %.1fs，后端=%s",
        len(config.boxes()), tol, timeout_s, type(backend).__name__,
    )
    return turntable, guard


def _load_image_bgr(path: str):
    """读一张图为 ndarray（BGR）。优先 cv2（Pi/PC 都有），退化到 PIL；都失败即 raise。"""
    import numpy as np

    try:
        import cv2  # noqa: PLC0415 - 延迟导入：主机无 cv2 时退化到 PIL

        img = cv2.imread(str(path))
        if img is not None:
            return img
    except Exception:  # noqa: BLE001 - 没有 cv2 就试 PIL
        pass
    try:
        from PIL import Image  # noqa: PLC0415

        with Image.open(str(path)) as im:
            arr = np.asarray(im.convert("RGB"))
        return arr[..., ::-1].copy()   # RGB → BGR
    except Exception as exc:  # noqa: BLE001
        raise BarrierCheckError("基准帧读不出：%s（%s）" % (path, exc)) from exc


def _snapshot_frame_provider(url: str, timeout_s: float):
    """返回一个"取一帧"的可调用对象（HTTP 快照口）。失败由调用方按 UNKNOWN 处理。"""
    import numpy as np

    def _fetch():
        import urllib.request  # noqa: PLC0415

        with urllib.request.urlopen(str(url), timeout=float(timeout_s)) as resp:
            data = resp.read()
        if not data:
            raise BarrierCheckError("快照口返回空（%s）" % url)
        try:
            import cv2  # noqa: PLC0415

            arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if arr is None:
                raise BarrierCheckError("快照解码失败（%s）" % url)
            return arr
        except ImportError:
            from io import BytesIO  # noqa: PLC0415

            from PIL import Image  # noqa: PLC0415

            with Image.open(BytesIO(data)) as im:
                return np.asarray(im.convert("RGB"))[..., ::-1].copy()

    return _fetch


def _build_barrier_checker(args, logger):
    """按 `--barrier-check` 装配挡板巡检器；off ⇒ None（主循环一行都不执行）。

    ⚠️ S3 **骨架**：判定逻辑/开关/配置已就位，但 ROI、基准帧、阈值必须等 M3 现场标定；
    配置不全时**启动即拒**（fail-closed），避免"以为开着其实没生效"。
    """
    mode = str(args.barrier_check).lower()
    if mode == "off":
        return None

    from dataclasses import replace  # noqa: PLC0415

    from electrical_control.rpi.barrier_check import (  # noqa: PLC0415
        BarrierChecker,
        load_barrier_config,
    )

    try:
        cfg = replace(load_barrier_config(args.config), mode=mode)
        baseline = _load_image_bgr(cfg.baseline_path)
        provider = _snapshot_frame_provider(cfg.snapshot_url, cfg.snapshot_timeout_s)
        checker = BarrierChecker(cfg, provider, baseline)
    except BarrierCheckError as exc:
        raise SystemExit("挡板巡检启用失败（fail-closed）：%s" % exc) from exc

    logger.warning(
        "挡板巡检已启用：mode=%s camera=%s roi=%s diff=%.3f on_unknown=%s"
        "（⚠️ S3 骨架：ROI/基准帧/阈值需 M3 现场标定；"
        "OCCUPIED 时\"能判 code 就当正常件抓\"分支尚未接入）",
        cfg.mode, cfg.camera, cfg.roi, cfg.diff_threshold, cfg.on_unknown,
    )
    return checker


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

    # 必须早于配置副作用、/dev/fb0、串口和视觉线程：拒绝时保证机构完全未接触。
    require_home_confirmation(args)

    # ---- 落料策略（2026-09-17 接线）：方案A 六固定盒 / 方案B 转盘选格 ----
    # 方案判定与校验都在 load_strategy_from_config 里：
    #   有 [TurntableAngles] 节 → 方案B（落料点固定，查转盘角度）
    #   否则                   → 方案A（读 [DropPoints]，且六盒必须齐全，缺一即 SystemExit）
    # 方案A 的校验与"缺货格就拒启动"行为与接线前【完全一致】，只是搬进了工厂函数。
    if demo:
        if (config_has_section(args.config, "TurntablePositions")
                or config_has_section(args.config, "TurntableAngles")):
            # --fake-link 主机冒烟：--config 里配了方案C 就按方案C 装配
            # （转盘后端换成 FakeBackend + 假索引）。没有这一支，"转盘接线"在主机上
            # 一行都执行不到，等于没测。
            strategy = load_strategy_from_config(args.config)
        else:
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

    # ---- 转盘守卫（2026-11-07：方案B 已接线）----
    #   方案B（[TurntableAngles]）→ PositionTurnGuard：读回位置值判到位（360° 位置域）
    #   方案C（[TurntablePositions]+[TurntableSides]）→ TurntableGuard：GPIO17 索引
    #   方案A（[DropPoints]）→ 两者皆 None ⇒ 主循环里转盘相关代码整体不执行
    turntable = None
    if strategy.requires_turntable_control() and not strategy.uses_drop_points():
        turntable, turn_guard = _wire_position_turntable(
            strategy, args.config, demo=demo, logger=logger
        )
    else:
        turn_guard = build_turn_guard(strategy, demo=demo)
    if turn_guard is not None and turntable is None:
        # 🔴 2026-09-22 加（安全加固，用户批准）：**链开工前先把转盘置回中位 1500µs**
        #    为什么：pw.txt 是链与常驻输出进程（/home/pi/pi_pw.py，见 /etc/init.d/S98turntable）
        #    之间的**唯一通路** —— 链只写文件，真正的 GPIO18 输出由那个常驻进程完成。
        #    实测事故：台架实验把 pw.txt 留成 **2155µs** ⇒ 舵机被持续驱到极限、一直动 ✗
        #    ⇒ 每轮开工写一次中位 = 清掉任何遗留值，避免"上一场实验的脉宽"被带上赛场。
        #    中位 1500 = turntable.TurntableConfig.zero_pulse_us（盘面「线 0」）。
        if not demo:
            try:
                # 2026-10-17：转盘已从「PWM 写 pw.txt」改为「ST-3215 总线舵机（UART2）」。
                # 这里改成走统一的 make_backend()，不再直接写文件 —— 否则新后端下写
                # pw.txt 是空操作（已没有进程读它），中位归零会静默失效。
                # 中位 1500µs = TurntableConfig.zero_pulse_us（盘面「线 0」）。
                from electrical_control.rpi.turntable import make_backend

                _be = make_backend()
                try:
                    _be.set_pulse_us(1500)
                    logger.info("转盘已置中位 1500µs（后端=%s）", type(_be).__name__)
                finally:
                    _be.close()
            except Exception as exc:  # noqa: BLE001 - 加固失败不阻断开工（会记警告）
                logger.warning("转盘中位置中失败（不阻断）：%s", exc)
        # 方案C 靠 payload.class_id 当货格号（校赛模式：BATCH_TARGETS 的 id 字节就
        # 承载 box_id，见 vision_ingest.BATCH_ID_BYTE_IS_BOX_ID）。形状模式下没有这个
        # 等价关系，转盘就不知道该不该翻 ⇒ 拒绝启动，而不是把每件都投到 A 侧。
        from electrical_control.rpi.vision_ingest import BATCH_ID_BYTE_IS_BOX_ID

        if not BATCH_ID_BYTE_IS_BOX_ID:
            raise SystemExit(
                "方案C 要求 payload.class_id 就是货格号（校赛模式 "
                "BATCH_ID_BYTE_IS_BOX_ID=True）；当前为形状模式，转盘无法判断该翻不翻。"
            )
        logger.warning(
            "方案C 已启用：开工自检会**真的转动转盘**。现场纪律：发 1500µs 时指针应"
            "仍停在盘面「线 0」，否则先重标定再开轮。"
        )
        try:
            turn_guard.preflight()
        except TurntableError as exc:
            raise SystemExit(
                f"转盘开工自检失败，拒绝启动（未打开串口、未开始轮次）：{exc}"
            ) from exc

    # ---- 方案B 开工自检（位置域，2026-11-07 接线）----
    if turntable is not None and not demo:
        # 开工回中位：位置域等价于旧的「写 1500µs」——清掉上一场遗留位置。
        # 注意 360° 六格并不以"中位"为货格 1；回中位只是安全起点，不参与落料坐标。
        try:
            turntable.goto_zero()
            logger.info("转盘已回中位（位置域，后端=%s）",
                        type(turntable.backend).__name__)
        except Exception as exc:  # noqa: BLE001 - 加固失败不阻断开工（会记警告）
            logger.warning("转盘回中位失败（不阻断）：%s", exc)
        try:
            turn_guard.preflight()
        except TurntableError as exc:
            raise SystemExit(
                f"转盘开工自检失败，拒绝启动（位置域读回不可用）：{exc}"
            ) from exc
        # 方案B 落料时转盘必须按「货格号」转；code 模式下 class_id 是 code(1..30)，
        # 不是货格号 ⇒ 必须开动态分配把 code 映射成 box_id，否则会按 code 转错格。
        from electrical_control.rpi.vision_ingest import BATCH_ID_BYTE_IS_BOX_ID

        if not BATCH_ID_BYTE_IS_BOX_ID and args.slot_mode != "dynamic":
            raise SystemExit(
                "方案B（[TurntableAngles]）在 code 模式下需要 --slot-mode dynamic："
                "class_id 是 code(1..30) 而不是货格号，没有动态分配就会按 code 转错格。"
                "（或改用 BATCH_TARGETS 校赛模式 BATCH_ID_BYTE_IS_BOX_ID=True。）"
            )
        logger.warning(
            "方案B 已启用（位置域转盘）：到位判据 = 读回位置与目标差 ≤ %d counts，"
            "超时/读不到 ⇒ 锁死停链。", turn_guard.config.tolerance_counts
        )

    # ---- 挡板巡检（S3，2026-11-07 骨架，默认 off）----
    barrier = _build_barrier_checker(args, logger)

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
    # 2026-11-07：`place_runtime` / `slot_allocator` 必须在分支**之前**初始化 ——
    # 它们只在真实模式分支里被赋值，而主循环无条件读它们 ⇒ 一进主循环就
    # UnboundLocalError（`--fake-link` 冒烟曾因此完全不可用）。
    # demo 模式本来就没有复看/动态分配（单件 class_id 直接是货格号），置 None 即正确语义。
    place_runtime = None
    slot_allocator = None
    box_id_resolver = None
    if args.slot_mode == "dynamic":
        # 2026-11-07（S2）：动态分配移到分支之前 —— demo 冒烟也要能验证
        # "code → box_id → 转盘格" 这条链；选格固定 1→6（已去两侧）。
        from electrical_control.rpi.slot_allocator import SlotAllocator

        slot_allocator = SlotAllocator(
            box_ids=(1, 2, 3, 4, 5, 6),
            mode="dynamic",
            journal_path=None if demo else args.slot_journal,
            round_id=round_id,
        )
        box_id_resolver = slot_allocator.box_for
        logger.info("货格动态分配：已启用（选格 1→6，台账=%s，round=%s）",
                    "(demo 不写台账)" if demo else args.slot_journal, round_id)
    if demo:
        scheduler.load_source(
            build_placeholder_source(round_id=round_id, round_task_id=round_task_id,
                                     demo=demo, items=max(1, int(args.demo_items)))
        )
    else:
        # 夹取策略（默认 off）：只在启用时构造排序器；构造失败自动退回 off（fail-safe）。
        payload_orderer = None
        # 2026-11-01（审核 D1）：「上一次落料点」—— 排序锚点与 five_key 落点键共用。
        last_drop_state: dict[str, object] = {"pt_mm": None}

        def _drop_point_memo(box_id: int):
            pt = strategy.get_drop_point(box_id)
            if pt is not None:
                # strategy.get_drop_point 返回 0.1mm 记账坐标 ⇒ 换算成物料装置坐标 mm
                last_drop_state["pt_mm"] = (pt[0] / 10.0, pt[1] / 10.0)
            return pt

        def _current_position_mm10():
            pt = last_drop_state["pt_mm"]
            if pt is None:
                return None
            return (int(round(pt[0] * 10.0)), int(round(pt[1] * 10.0)))

        def _last_drop_point():
            from electrical_control.pick_strategy.geometry import Point as _Pt
            pt = last_drop_state["pt_mm"]
            return None if pt is None else _Pt(pt[0], pt[1])

        if args.pick_strategy == "order":
            from electrical_control.pick_strategy.chain_adapter import (
                payload_orderer_from_ini,
            )
            from electrical_control.pick_strategy.orderer import SettleTracker

            settle_tracker = None
            if args.order_mode == "five_key":
                settle_tracker = SettleTracker(
                    settle_frames=max(1, int(args.settle_frames)),
                    settle_shift_mm=float(args.settle_shift_mm),
                )

            resolved_mode = None if args.order_mode == "auto" else args.order_mode
            payload_orderer = payload_orderer_from_ini(
                args.pick_strategy_config,
                order_mode=resolved_mode,
                settle=settle_tracker,
                last_drop_provider=_last_drop_point,
            )
            if payload_orderer is None:
                logger.warning(
                    "夹取策略：--pick-strategy=order 但排序器构造失败 ⇒ 本次退回默认排序"
                )
            else:
                logger.info(
                    "夹取策略：已启用（α：只改顺序、不丢件）；order_mode=%s 配置=%s",
                    "配置 [Strategy] order_mode" if args.order_mode == "auto" else args.order_mode,
                    args.pick_strategy_config,
                )
        # 2026-11-02：主动放弃难夹形状（为得分）。规则放在 pick_strategy.ini 的
        # [Strategy] skip_shapes（0=全抓，3=圆柱，5=圆锥）。默认 0 ⇒ 行为不变。
        class_id_filter = None
        try:
            from electrical_control.pick_strategy.config import build_config as _build_pcfg
            from electrical_control.pick_strategy.selector import shape_of_class_id

            _pc = _build_pcfg(args.pick_strategy_config)
            _skip = tuple(getattr(_pc, "skip_shapes", ()) or ())
            _cid_mode = getattr(_pc, "class_id_mode", "box_id")
            if _skip:
                class_id_filter = (
                    lambda cid, _s=_skip, _m=_cid_mode:
                    shape_of_class_id(cid, _m) in _s
                )
                logger.warning("主动放弃形状：跳过分拣 %s（class_id_mode=%s）",
                               _skip, _cid_mode)
        except Exception:
            logger.warning("读取 skip_shapes 失败：本次不跳过任何形状", exc_info=True)

        # 2026-11-01（动态分配）：code → box_id。装配已上移到 `if demo:` 之前
        # （2026-11-07 S2：demo 也要验证 code→box_id→转盘格）。这里不再重复构造。

        # 2026-11-01：落料位复看（默认 off）。复用同一个 slot_allocator 做台账纠正。
        place_runtime = None
        if args.verify_place != "off":
            from electrical_control.rpi.place_eye import load_place_eye_config
            from electrical_control.rpi.place_verify_runtime import PlaceVerifyRuntime

            eye_cfg = load_place_eye_config(args.place_eye_config or args.config)
            if eye_cfg is None:
                logger.warning("落料位复看：--verify-place=%s 但 [PlaceEye] 未启用/未标定"
                               "⇒ 本次按不可用处理（统计记 UNKNOWN）", args.verify_place)
            place_runtime = PlaceVerifyRuntime(
                args.verify_place, cfg=eye_cfg, allocator=slot_allocator)
            monitor.place_runtime = place_runtime
            logger.info("落料位复看：已启用 %s（配置=%s）",
                        args.verify_place, args.place_eye_config or args.config)

        source = build_socket_source(
            round_id=round_id,
            round_task_id=round_task_id,
            drop_point_for_box=_drop_point_memo,
            calibration_config=args.calibration_config,
            fixed_pick_point=fixed_pick_point,
            payload_orderer=payload_orderer,
            box_id_resolver=box_id_resolver,
            class_id_filter=class_id_filter,
            current_position_provider=(_current_position_mm10
                                      if args.anchor == "last_drop" else None),
            first_dispatch_settle_frames=args.first_dispatch_settle,
            first_dispatch_max_wait_s=args.first_dispatch_max_wait,
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
    # 🔴 2026-09-22：本轮已完成件列表（R-D03 逐件累加表格）。链一轮一个进程 ⇒ 生命周期即本轮 ✓
    completed_rows: list = []
    # 段2 的待显示载荷：MOTION_DONE 时记下，等规则帧出完再落屏（见该分支注释）
    success_info: TwoStageInfo | None = None
    # 超时重传状态：记录上次派发/重传时间和任务上下文
    last_task_sent_at = 0.0
    last_task_context = None
    task_timeout_s = 5.0  # 5s 无 MOTION_DONE/ITEM_RESULT → 重传
    # 🔴 2026-09-21 新增：板子明确拒收（NACK）时的重试退避。
    #   实机证据（R3/R4 两轮）：每件成功收 DISPLAY_ACK 之后，链**立刻**派下一件，
    #   而板子此时还没收尾完、没进到 WAIT_TASK ⇒ 回 NACK_ACK_NOT_APPLICABLE +
    #   NACK_SINGLE_TASK_ONLY。旧代码把 NACK 落到最后的 else 分支**只打日志、不重试**，
    #   于是只能干等满 task_timeout_s 才重传 ⇒ **每件白拖 ~8 秒（实测 21~22s/件）**。
    #   这里改成"收到 NACK 立刻带小退避重发"：0.3s 是留给板子"收尾上一件 → 进
    #   WAIT_TASK"的时间，避免把 NACK 打成死循环。
    #   🔴 2026-09-22 二次修（实机 round-R8-074808 与 round-R8-075954 连续两轮同一位置死）：
    #     4 次失败（0.3s 退避 ×5 = 约 1.5s）**不够**板子收尾 —— 两轮都在"派第 2 件"处
    #     被 NACK_ACK_NOT_APPLICABLE + 4×NACK_SINGLE_TASK_ONLY 打满上限、fail-closed 收场。
    #     故把退避与上限放大到大约 6 秒（12 × 0.5s）。为什么加大是安全的：
    #     **只有"板子还没准备好"这一类的 NACK 才走重试**（_nack_is_retryable 判别，
    #      WRONG_ROUND / STALE_OR_ORDER / TASK_REJECTED / 未知码一律立即 fail-closed）
    #     ⇒ 放大预算只会多等，不会把"必然被拒"的帧打成死循环。
    #     ⚠️ 代价：板子真的卡住时，从 1.5s 变成约 6s 才收场（仍远短于空闲钟）。
    nack_retry_backoff_s = 0.5
    # 🔴 2026-09-22 修复（F3）：NACK 重试**必须有上限**（原因码判别见 _nack_is_retryable）。
    #   旧行为无上限 ⇒ 见该函数上方的说明。上限按"每件"计，派件时清零。
    nack_retry_max = 50   # 2026-09-23：25s 窗口，等板子跑完上一件
    nack_retries = 0
    # 🔴 2026-09-22 新增（N2 / F6）：**两支钟**的整轮收场看门狗。
    #   空闲钟 idle_since：只在【没有运动在飞】时走 ⇒ 只有"台面没件了"才会到点。
    #   在飞钟 inflight_since：从发令起走，收到 MOTION_DONE/ITEM_RESULT 就清
    #                            ⇒ 只有"板子静默"才会到点。
    # ⚠️ 为什么不能用单钟 15s：实测第一件 发令→MOTION_DONE = **15.154s > 15s**（18:55 轮），
    #    单钟 15s 会在**正常**的件上误判 ⇒ 把好轮判死。这是拿实测数据改的设计。
    # ⚠️ 重置只认"MOTION_DONE 到"与"ITEM_RESULT→上屏"；**不认 ITEM_TASK sent**
    #    （只证明主机发了命令，不证明装置动了）。
    # ⚠️ 收场时**不得**向 STM32 发 STOP ALL / HOME / RESET —— 见收场分支的注释。
    # ⚠️ 本改动前，链**永远不会自己退出**：静默时空转、有在飞件时每 5s 重传直到人工 Ctrl-C。
    round_idle_timeout_s = float(args.round_idle_timeout)
    inflight_timeout_s = float(args.inflight_timeout)
    idle_since = time.monotonic()
    inflight_since: float | None = None
    while True:
        if scheduler.is_faulted:
            cl.record(FAULT, now=time.monotonic(), detail="scheduler FAULT, 链路停止")
            logger.error("scheduler FAULT，链路停止（fail-closed）")
            return 1

        # 0) 转盘到位校验（仅方案C）：放在派件**之前** —— 上一件若没翻到位，这一件不许发。
        if turn_guard is not None:
            turntable_fault = turn_guard.poll()
            if turntable_fault is not None:
                cl.record(FAULT, now=time.monotonic(), detail=turntable_fault)
                logger.error("转盘故障，链路停止（fail-closed）：%s", turntable_fault)
                return 1

        # 1) 派发下一件（R-D04：未完成显示前返回 None）
        task = scheduler.next_task()
        if task is not None:
            # 1a-0) 挡板巡检（S3，2026-11-07 骨架，默认 off）：**去落料点之前**看一眼挡板上
            #       有没有被崩飞的件（D6/L76）。设计口径：只判"有/无"，不细分类；
            #       OCCUPIED 且能判 code ⇒ 当正常件抓（上层分支，骨架未接）；判不出 ⇒ 夹爪停住；
            #       取图失败/判不出 ⇒ UNKNOWN，按 [BarrierCheck] on_unknown 决定继续/停链。
            if barrier is not None:
                state, evidence = barrier.check()
                is_stop_mode = barrier.config.mode == "stop"
                if state is BarrierState.OCCUPIED:
                    cl.record(STAGE, now=time.monotonic(),
                              detail="挡板巡检=OCCUPIED %s" % (evidence,))
                    if is_stop_mode:
                        logger.error("挡板上有件（%s）⇒ 停链（fail-closed）；"
                                     "现场需把件清走再继续", evidence)
                        cl.record(FAULT, now=time.monotonic(),
                                  detail="挡板巡检发现有件，停链")
                        return 1
                    logger.warning("挡板巡检=OCCUPIED（observe 档：只记录，不拦截）：%s",
                                   evidence)
                elif state is BarrierState.UNKNOWN:
                    cl.record(STAGE, now=time.monotonic(),
                              detail="挡板巡检=UNKNOWN %s" % (evidence,))
                    action = unknown_action(barrier.config)
                    if action == "stop" and is_stop_mode:
                        logger.error("挡板巡检没看清且 on_unknown=stop ⇒ 停链：%s", evidence)
                        cl.record(FAULT, now=time.monotonic(),
                                  detail="挡板巡检 UNKNOWN，按 on_unknown=stop 停链")
                        return 1
                    logger.warning("挡板巡检=UNKNOWN（%s）：按 on_unknown=%s 继续",
                                   evidence, barrier.config.on_unknown)
                else:
                    logger.debug("挡板巡检=CLEAR")
            # 1a) 转盘预置（仅方案C）：**发 ITEM_TASK 之前**下发脉宽，但**不等整定**。
            #     写 pw.txt 是 O(1) 原子替换；真正的转角由常驻 pi_pw.py（每 0.1s 读一次）
            #     与舵机在滑台约 12s 的行程里完成 ⇒ **转盘与滑台并行**
            #     （2026-09-21 用户裁决：转盘动作计入 15s 失活窗，串行会白吃 1~2s 余量）。
            #     越界 / 锁定 / 缺配置 ⇒ 本件不发、停链（绝不"表还在转着"就落料）。
            #     `payload.class_id` **就是货格号**（校赛模式，见 vision_ingest），
            #     所以这里零协议改动：ITEM_TASK 的 12 字节一个都没动。
            if turn_guard is not None:
                # 2026-11-01（协议 V1.0）：code(1..30) 下 class_id **不再是货格号**，
                # 必须先映射成 box_id(1..6) 再下发转盘；否则转盘会转到错角度。
                # 默认 static + box_id 模式下 tt_box == payload.class_id，行为与改动前一致。
                tt_box = int(task.payload.class_id)
                if slot_allocator is not None:
                    try:
                        mapped = slot_allocator.box_for(tt_box)
                        if mapped is not None:
                            tt_box = int(mapped)
                        else:
                            logger.error("转盘预置失败：code=%d 无可用货格（分配器满）"
                                         "⇒ 本件不发，停链", tt_box)
                            cl.record(FAULT, now=time.monotonic(),
                                      detail="货格分配器满，无法预置转盘")
                            return 1
                    except Exception:
                        logger.warning("货格映射失败：沿用 class_id 作货格号", exc_info=True)
                try:
                    refused = turn_guard.before_dispatch(tt_box)
                except TurntableError as exc:
                    cl.record(FAULT, now=time.monotonic(), detail=f"转盘拒绝动作: {exc}")
                    logger.error("转盘拒绝动作，本件不发 ITEM_TASK，链路停止：%s", exc)
                    return 1
                if refused is not None:
                    cl.record(FAULT, now=time.monotonic(), detail=refused)
                    logger.error("转盘侧配置缺失，停链（fail-closed）：%s", refused)
                    return 1
            raw = outbound.send_item_task(task)  # ITEM_TASK 出站（状态 → WAIT_MOTION_DONE）
            done_items += 1
            # 2026-11-01：每 4 件打一条落料位复看统计（含 MATCH/MISMATCH/UNKNOWN 计数）
            if (place_runtime is not None and place_runtime.enabled()
                    and done_items % 4 == 0):
                logger.info(place_runtime.summary())
            last_task_sent_at = time.monotonic()
            last_task_context = task
            success_info = None  # 新的一件：清掉上一件遗留的「分拣成功」载荷
            inflight_since = time.monotonic()  # N2-b：在飞钟从发令起走
            nack_retries = 0                   # F3：NACK 重试上限按件重置

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
            # 段1：识别到待分拣物体 → 该物体信息。
            # 🔴 2026-09-22 实测改（R-D03）：**只在"本轮第一件"之前画一次**。
            #    原因：段1 是两行文字（**无货物图片、无分拣成功总数量**），而它是在"下一件 ITEM_TASK
            #    之后"画的 ⇒ 会把上一件的**合规四栏帧**盖掉 —— 实测四栏帧只活 0.08 秒
            #    （round-R8-202828.log：20:28:41.328 显示完成并确认 → 20:28:41.408 两段显示已上屏）。
            #    改为只画一次后，屏上**始终**是"最近一件的四栏"（序号/名称/图片/总数量），
            #    直到下一件的合规帧到来 ⇒ 符合 R-D03「每件存盒后显示四栏」与 R-R03 的时序 ✓
            #    done_items 是本轮已派件数（本条 ITEM_TASK 已在上文 +1）⇒ ==1 即"本轮第一件"，按轮自然重置。
            # 失败只记 ERROR，不停链（见 _show_two_stage）。
            if done_items == 1:
                _show_two_stage(
                    two_stage.show_recognized,
                    _two_stage_info(task, names, seq_no=done_items),
                    logger,
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
        # 🔴 2026-09-22 修复（F4）：**必须同时要求"还在等 MOTION_DONE"**。
        #   旧判据只看"有在飞件 + 超时"，于是 MOTION_DONE 早已到达、只差 ITEM_RESULT 时
        #   也会重发同一帧 ⇒ 板子按 dedup 只回缓存 ACK（不是 ITEM_RESULT）⇒
        #   Pi 永远停在 WAIT_ITEM_RESULT、每 5s 重传一次且**无出口**（死锁）；
        #   叠加"板子自愈时会清 dedup、把重发帧当全新首件重新执行运动"，
        #   还会造成**同一件被搬两次**。
        #   同文件另一条重传路径 _should_resend_on_barrier_ready 本来就查状态，这里补齐一致。
        if (last_task_context is not None
                and scheduler.state is SchedulerState.WAIT_MOTION_DONE
                and (time.monotonic() - last_task_sent_at) > task_timeout_s):
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

        # 2b) 整轮收场看门狗（N2 / F6）：两支钟，见循环前注释。
        #     在飞钟优先：发令后板子一直静默 ⇒ 记 FAULT、干净收场（退出 1）。
        #     空闲钟：没有运动在飞、且长时间没有新件 ⇒ 判本轮结束（退出 0）。
        # ⚠️ 两处收场**都不向 STM32 发任何命令**（不发 STOP ALL / HOME / RESET）：
        #    板子应保持现状，由操作员按现场流程处理。
        now_mono = time.monotonic()
        close_reason = _round_close_reason(
            now=now_mono,
            inflight_since=inflight_since,
            idle_since=idle_since,
            inflight_timeout_s=inflight_timeout_s,
            round_idle_timeout_s=round_idle_timeout_s,
        )
        if close_reason == "inflight":
            assert inflight_since is not None  # _round_close_reason 的契约
            cl.record(
                FAULT,
                now=time.monotonic(),
                detail=f"在飞 {now_mono - inflight_since:.1f}s 无 MOTION_DONE（阈值 "
                f"{inflight_timeout_s:.1f}s）：判板子静默",
            )
            logger.error(
                "在飞 %.1fs 无 MOTION_DONE/ITEM_RESULT（阈值 %.1fs）⇒ 判板子静默，"
                "干净收场，退出码 1。**不向 STM32 发任何停止/复位命令**",
                now_mono - inflight_since, inflight_timeout_s,
            )
            return 1
        elif close_reason == "idle":
            cl.record(
                STAGE,
                now=time.monotonic(),
                detail=f"空闲 {now_mono - idle_since:.1f}s 无新件（阈值 "
                f"{round_idle_timeout_s:.1f}s）：判本轮结束",
            )
            logger.info(
                "空闲 %.1fs 无新件（阈值 %.1fs）⇒ 判本轮结束，干净收场，退出码 0。"
                "**不向 STM32 发任何停止/复位命令**",
                now_mono - idle_since, round_idle_timeout_s,
            )
            break

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
            # 转盘（仅方案C）：核对"本件落料时转盘是否已经确认到位"。
            # 正常情况下转盘在派件那一刻就起转、滑台要走十余秒，_expect 早已清空；
            # 若此刻仍在等校验 ⇒ 本件可能在转盘旋转中落料 ⇒ 锁死停链。
            if turn_guard is not None:
                turn_guard.note_motion_done()
                if turn_guard.failed is not None:
                    cl.record(FAULT, now=time.monotonic(), detail=turn_guard.failed)
                    logger.error("转盘到位校验失败，链路停止：%s", turn_guard.failed)
                    return 1
            # 重置超时计时：已收到 MOTION_DONE，等待 ITEM_RESULT
            last_task_sent_at = time.monotonic()
            # N2：MOTION_DONE 是**可观测进展** ⇒ 清在飞钟、重置空闲钟、清 NACK 计数
            inflight_since = None
            idle_since = time.monotonic()
            nack_retries = 0
            # 段2 的触发点（2026-09-18 用户拍板：以 STM32 报**动作完成**为准，不等转盘到位）。
            # 这里只**记下**载荷、不画：MOTION_DONE 与 ITEM_RESULT 通常几毫秒内先后到达，
            # 此刻画出的「分拣成功」会被紧接着的规则帧盖掉（肉眼看不到）。
            # 所以改在规则帧（_render_and_ack）之后落屏 → 一直留在屏上，直到下一件的段1。
            # 结果码要到 ITEM_RESULT 才知道，是否真失败也在那里判。
            current = scheduler.current_task
            # seq_no=done_items：MOTION_DONE 这一刻还没派下一件 ⇒ done_items 仍是**本件**的号
            # （因此段1/段2 显示同一个序号）。⚠️ 值在此**冻结进载荷**，不受后续递增影响。
            success_info = (
                _two_stage_info(current, names, seq_no=done_items)
                if current is not None
                else None
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
                            frame_output, font_path, cl, logger,
                            seq_no=done_items,
                            completed_rows=completed_rows)
            # N2：本件已走完整条显示闭环（规则帧 + DISPLAY_ACK）⇒ 重置空闲钟。
            # 下一件若在 round_idle_timeout_s 内不来，就判本轮结束。
            idle_since = time.monotonic()
            # 🔴 2026-09-22 DSH 改（赛规 R-D03 / R-R03）：**不再**在规则帧之后落「分拣成功」两段显示。
            #   原注释自承"规则帧之后再落屏，于是「分拣成功」留在屏上" ⇒ 实际后果是：
            #   屏上常态是【缺货物图片、缺分拣成功总数量】的两段显示帧，而合规四栏帧
            #   （序号/货物名称/图片/分拣成功总数量，由 HdmiDisplayRenderer 画出）只在屏上活了几十毫秒被盖掉 ✗。
            #   ⇒ 现改为：**让合规四栏帧成为本件最后落屏的一帧** ✓
            #   （show_success/_compose_success 与两段显示的段1「识别到待分拣物体」都保留不动 ⇒ 随时可回退；
            #     上面 success_info 的计算暂时成为死代码，不删除，避免扩大改动面。）
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
            # 未建模命令落在这里（gateway.py:196 的兜底 return）。
            # ⚠️ 2026-09-22 更正：**ACK/NACK 不在这里** —— 它们由
            # gateway._handle_ack_nack 建模，事件名是 "ACK_ACCEPTED" / "NACK_*"
            # （见 :199-228）。本注释原先写"ACK/NACK 在此出现"是错的。
            logger.info("inbound: IGNORED（未建模命令）")
        elif event == "ACK_ACCEPTED":
            # 🔴 A5（2026-09-22）：板子**明确受理**了在飞的那一帧 ⇒ 停该件的 5s 超时重传。
            #   修前：收到 MOTION_DONE 只重置 last_task_sent_at，**没清 last_task_context**，
            #   而在飞判据只看"有上下文 + 超时" ⇒ 没收到 ITEM_RESULT 之前每 5s 重传一次
            #   （实机一轮 23 次）。判据与理由见 _should_stop_resend_on_ack_accept()。
            #
            # 🔴 2026-09-22 三次修（前两次都错了，记下来别再犯）：
            #   ① 原文用 `frame.task_id` —— 本循环的 `frame` 是 `link.receive()` 的**原始
            #      bytes**（:1544），解析它的是 `gateway.feed_frame(frame)`（:1552）
            #      ⇒ AttributeError: 'bytes' object has no attribute 'task_id'
            #        （实机 round-R8-075620 整条链退出）。
            #   ② 改成读 `gateway._last_inbound_frame` —— **该属性不存在**
            #      （hasattr 恒 False）⇒ 永远取到 None ⇒ fail-closed、静默失效
            #        （实机 round-R8-075954 日志：`ACK_ACCEPTED task_id=None`）。
            #   ③ 正解：身份由 gateway 的 outcome 带出来
            #      （`PiGatewayOutcome.task_id`，在 `_handle_ack_nack` 里填 —— 那里拿到
            #       的就是**解析后**的帧，见 electrical_control/rpi/gateway.py:210-240）。
            ack_task_id = outcome.task_id
            if _should_stop_resend_on_ack_accept(last_task_context, ack_task_id):
                logger.info(
                    "inbound: ACK_ACCEPTED（task_id=%s 已被板子受理 ⇒ 停该件重传）",
                    ack_task_id,
                )
                last_task_context = None
            elif last_task_context is None:
                logger.info("inbound: ACK_ACCEPTED（没有在飞的件，忽略；不动机械）")
            else:
                logger.warning(
                    "inbound: ACK_ACCEPTED task_id=%s 与在飞件 task_id=%d 不符"
                    " ⇒ 不清重传状态（宁可多传一次，也不误清别件的在飞上下文）",
                    ack_task_id,
                    last_task_context.task_id,
                )
        elif isinstance(event, str) and event.startswith("NACK"):
            # 🔴 2026-09-21：板子**明确拒收**在飞的那一帧（典型：NACK_SINGLE_TASK_ONLY
            #    —— 它还没进到 WAIT_TASK）。必须**立刻带小退避重发**，
            #    不能等满 task_timeout_s（旧行为每件白拖 ~8s，实测 21~22s/件）。
            # 🔴 2026-09-22 修复（F3）：**加原因码判别 + 次数上限**。
            #    只有"板子还没准备好收这一件"类的原因值得重发（见 _nack_is_retryable）；
            #    WRONG_ROUND / STALE_OR_ORDER / TASK_REJECTED / 未知码这类
            #    重发同一字节必然再被拒 ⇒ 直接 fail-closed 收场，绝不进重试循环。
            retryable = _nack_is_retryable(event)
            nack_retries += 1
            if last_task_context is None:
                logger.warning("收到 %s 但没有在飞的件：忽略（不进队列、不动机械）", event)
            elif not retryable:
                cl.record(
                    FAULT,
                    now=time.monotonic(),
                    detail=f"{event}：该原因重发必然再被拒，fail-closed 收场",
                )
                logger.error(
                    "inbound %s：板子拒收，且**重发同一帧必然再被拒**（原因码类）"
                    "⇒ 本轮收场，不重发（旧行为会在此无限重发）。退出码 1",
                    event,
                )
                return 1
            elif nack_retries > nack_retry_max:
                cl.record(
                    FAULT,
                    now=time.monotonic(),
                    detail=f"{event}：NACK 重试超过 {nack_retry_max} 次，fail-closed 收场",
                )
                logger.error(
                    "inbound %s：NACK 重试已达上限 %d 次 ⇒ 本轮收场（不再重发），退出码 1",
                    event, nack_retry_max,
                )
                return 1
            else:
                cl.record(
                    TASK,
                    now=time.monotonic(),
                    detail=f"inbound {event}（第 {nack_retries}/{nack_retry_max} 次重试）",
                )
                logger.warning(
                    "inbound %s：板子拒收本帧，%.1fs 后重发"
                    "（第 %d/%d 次，不再等 %.1fs 超时）",
                    event, nack_retry_backoff_s, nack_retries, nack_retry_max,
                    task_timeout_s,
                )
                time.sleep(nack_retry_backoff_s)
                try:
                    raw_resend = outbound.resend_item_task(last_task_context)
                except Exception:
                    logger.warning("NACK 后重发失败（保留在飞状态，等超时重传）", exc_info=True)
                else:
                    last_task_sent_at = time.monotonic()
                    cl.record(
                        TASK,
                        now=time.monotonic(),
                        detail=f"NACK({event}) 后重发 ({len(raw_resend)}B)",
                    )
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
