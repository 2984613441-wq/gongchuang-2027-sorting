"""MaixCAM / MaixVision 单文件：V6 颜色分离稳定版 **+ 树莓派发送桥**。

【这个文件是什么】
朋友的 V6 原文（`stage1_color_v6_stable.py`）**一个字都没改**，
只在最上面加了发送桥、在 main() 里插了 2 行。
→ 打开这个文件、点运行，就会一边在屏幕上画框、一边把结果发给树莓派。

【和原版 V6 的差异，只有 3 处（用 <<<V6-BRIDGE>>> 标出）】
  1. 顶部多了一段「发送桥」代码
  2. main() 里 tracker 之后：  sender = BatchSender()
  3. 循环里 update 之后：      sender.send(results)
  （外加 finally 里 sender.close()）

【识别逻辑完全没动】颜色阈值、形状映射、稳定/平滑/HOLD 全部照旧。

【线上格式（已冻结，不要改）】
BATCH_TARGETS：target_count(1) + task_id(2,BE) + target[N]，每 target 7 字节：
    id_byte(1) + confidence(1,0-100) + X(2,BE) + Y(2,BE) + angle(1,0xFF)
校赛模式下 id_byte 填 box_id(1..6)（用户 2026-09-17 批准，台账 §2.1）。
V6 的 `bin` 字段就是货格号，直接当 id_byte。

【出问题先看这三条】
  · 树莓派要先在 8765 监听，否则这里会打 connect failed（不致命，会一直重试）
  · bin=None（HOLD 灰框）不会发出去 —— 这是对的
  · 像素坐标原样透传（320 系），换算口径由树莓派侧负责
"""
import os
import time

import cv2
import numpy as np

# <<<V6-BRIDGE>>> 发送桥所需的额外 import
import socket
import struct

# ────────────────────────────────────────────────────────────────────────────
# 2026-10-23 新增：几何形状判定（可选，默认关闭）
#
# 背景：《2026年智能分拣赛项补充说明》把物料改成 **5 色 × 6 形状解耦**
#   （正方体/长方体/圆柱/五棱柱/圆锥/正四面体），
#   而本文件原来的 COLOR_TO_MATERIAL 是「颜色→形状」硬编码查表
#   （校赛"颜色唯一确定货物"的做法），新规则下 100% 失效。
#
# 开关：USE_GEOMETRY_SHAPE = False ⇒ 行为与接入前**逐字节相同**
#                               = True  ⇒ 形状改由轮廓几何判定，颜色只用于
#                                          日志/取证，不参与分箱决策
#
# ⚠️ 默认 False 是刻意的：本文件跑在 MaixCAM 上，主机测试覆盖不到。
#    必须先实机验证再开。
#
# ⚠️ 开启后 `shape_geometry_lite.py` 必须与本文件**一起**拷到 MaixCAM。
#    该模块与 `sorting_vision/shape_geometry.py` 由
#    `视觉/tests/test_shape_geometry_parity.py` 逐一对拍防止漂移。
# ────────────────────────────────────────────────────────────────────────────
USE_GEOMETRY_SHAPE = os.environ.get("USE_GEOMETRY_SHAPE", "0") == "1"

_shape_lite = None
if USE_GEOMETRY_SHAPE:
    try:
        import shape_geometry_lite as _shape_lite  # 同目录部署
    except ImportError:
        # 找不到模块就退回旧路径，绝不让视觉整个挂掉
        USE_GEOMETRY_SHAPE = False

# <<<V6-BRIDGE>>> ================= 发送桥开始 =================
GATEWAY_HOST = "172.20.10.8"   # 树莓派
GATEWAY_PORT = 8765
TASK_ID = 1                    # ⚠️ 绝不能是 0（树莓派 task_id 对不上会整批丢）
ENABLE_NETWORK = True          # 先设 False 可以只打印不发，用于单独调视觉
MIN_SEND_INTERVAL_S = 0.10     # 发送节流；V6 最高 6 FPS，不必每帧都发

_ANGLE_NONE = 0xFF
_TARGET_BYTES = 7

# ════════════════════════════════════════════════════════════════════════════
# 2026-10-26 新增：(形状, 颜色) → code(1..30) 编码（省赛新协议）
#
# 背景：《2026年智能分拣赛项补充说明》把物料改成 **5 色 × 6 形状解耦**，
#      `code` 同时编码形状和颜色，范围 1~30，且 `code` 就是屏幕图片的 `image_id`
#      （30 张图 `1.png`~`30.png`，见 `_screen_assets/colored/manifest.json`）。
#
# 编码公式（冻结，见 manifest.json L2）：
#     code = (shape_id - 1) * 5 + color_id + 1
#
# shape_id 映射（必须严格按顺序，见 manifest.json L3-10）：
SHAPE_TO_ID = {
    "cube": 1,               # 正方体
    "cuboid": 2,             # 长方体
    "cylinder": 3,           # 圆柱
    "pentagonal_prism": 4,   # 五棱柱
    "cone": 5,               # 圆锥
    "tetrahedron": 6,        # 正四面体
}

# color_id 映射（见 manifest.json L19-25）：
COLOR_TO_ID = {
    "red": 0,
    "yellow": 1,
    "green": 2,
    "blue": 3,
    "white": 4,
}


def code_of(shape: str, color: str):
    """(形状, 颜色) → code(1..30)。无法映射时返回 None。

    省赛新协议：id_byte 不再是 bin_id(1..6)，而是 (shape, color) 打包码。
    下游树莓派侧需同步改 BATCH_ID_BYTE_IS_BOX_ID = False 才能解开。
    """
    shape_id = SHAPE_TO_ID.get(shape)
    color_id = COLOR_TO_ID.get(color)
    if shape_id is None or color_id is None:
        return None
    return (shape_id - 1) * 5 + color_id + 1
# ════════════════════════════════════════════════════════════════════════════


def encode_target(row):
    """把一个 V6 result 编成 7 字节。

    ## 双协议（2026-10-26 修正）

    之前 AI-2 把本函数**无条件**改成输出 `code(1..30)`，导致严重回归：
    默认路径（`USE_GEOMETRY_SHAPE=False`）下 `COLOR_TO_MATERIAL` 给出的是
    旧形状名（`triangular_prism` / `unknown`），`code_of()` 映射不出来
    ⇒ 红/蓝/黄/白**全部返回 None** ⇒ 一件都发不出去 ⇒ 树莓派 15s 无动作
    ⇒ **本轮比赛结束**。同时破坏了 3 个线格式测试（test_50/51/54）。

    ⇒ 现在按开关分叉，两条路径互不影响：

    **USE_GEOMETRY_SHAPE = False（默认）**
        `id_byte = bin_id(1..6)`，**逐字节等同原实现**
        下游 `vision_ingest.py` 保持 `BATCH_ID_BYTE_IS_BOX_ID = True`

    **USE_GEOMETRY_SHAPE = True（省赛新协议）**
        `id_byte = code(1..30) = (shape_id-1)*5 + color_id + 1`
        ⚠️ 下游**必须同一个 PR 做两件事**，否则全部拒识 → 15s → 本轮结束：
          ① `vision_ingest.py` 改 `BATCH_ID_BYTE_IS_BOX_ID = False`
          ② 补 `group_table` 负责把 code 分配成 box_id
    """
    if USE_GEOMETRY_SHAPE:
        # ── 新协议：id_byte = code(1..30) ────────────────────────────
        shape = row.get("shape")
        color = row.get("color")
        code = code_of(shape, color) if (shape and color) else None
        if code is None:
            # 形状/颜色映射不出来 ⇒ 不发这一件（下游会当"没看见"处理，
            # 不会像 bin_id=None 那样触发整批拒识）
            return None
        if not (1 <= code <= 30):
            return None                       # 双保险
        id_byte = code

        # confidence 语义（2026-10-26 明确）= min(颜色置信, 形状置信)
        # 理由：下游用 `confidence < 50` 判「待定」，形状不确定比颜色不确定
        #       更危险（混装 0 分），取 min 确保两者都够确定才发货。
        color_conf = int(round((row.get("color_fraction") or 0.0) * 100))
        shape_conf = int(row.get("shape_confidence", 100))
        # TODO: 几何判定目前不输出 shape_confidence（默认满分 100），
        #       后续应补：圆形度、长宽比偏差、轮廓多边形拟合残差 归一化到 0~100。
        conf = max(0, min(100, min(color_conf, shape_conf)))
    else:
        # ── 旧协议：id_byte = bin_id(1..6)，逐字节等同原实现 ──────────
        # ⚠️ 这段**不要**改成走 code_of —— COLOR_TO_MATERIAL 给的是旧形状名，
        #    映射不出来。整段保持原样是刻意的向后兼容保证。
        bin_id = row.get("bin")
        if bin_id is None:
            return None          # HOLD 灰框 / 未知颜色 —— 不发货格，也不发这一件
        if not isinstance(bin_id, int) or not (1 <= bin_id <= 6):
            return None
        id_byte = bin_id
        # confidence：V6 没有 score，只有 color_fraction。这是【合成值】，不是模型置信度。
        frac = row.get("color_fraction") or 0.0
        conf = max(0, min(100, int(round(frac * 100))))

    left, top, w, h = row["bbox"]
    # F1(2026-09-21)：A' 的形心只有在这里被读到才算生效。
    # 没有 "center" 键（旧 row / 对称形状回落的旧路径）⇒ 逐字节等同原实现。
    cx, cy = row.get("center") or (int(left + w / 2), int(top + h / 2))
    if not (0 <= cx <= 0xFFFF and 0 <= cy <= 0xFFFF):
        return None

    return struct.pack(">BBHHB", id_byte, conf, cx, cy, _ANGLE_NONE)


def encode_batch_targets(rows, task_id):
    """把若干 V6 result 编成完整的 BATCH_TARGETS 数据区。bin=None 的会被丢掉。"""
    if not isinstance(task_id, int) or not (0 <= task_id <= 0xFFFF):
        raise ValueError("task_id 必须落在 0..65535")
    if task_id == 0:
        print("[V6-BRIDGE] WARNING: task_id=0，树莓派可能整批丢弃")
    payload = bytearray()
    for row in rows:
        packed = encode_target(row)
        if packed is not None:
            payload += packed
    count = len(payload) // _TARGET_BYTES
    if count > 255:
        raise ValueError("target_count 是 1 字节，不能超过 255")
    return bytes([count]) + struct.pack(">H", task_id) + bytes(payload)


class BatchSender:
    """带重连的 TCP 发送器。一帧一件都没认出来时不发（不占树莓派的槽）。"""

    def __init__(self, host=GATEWAY_HOST, port=GATEWAY_PORT, task_id=TASK_ID,
                 enable=ENABLE_NETWORK, interval=MIN_SEND_INTERVAL_S):
        self._host = host
        self._port = port
        self._task_id = task_id
        self._enable = enable
        self._interval = interval
        self._sock = None
        self._last = 0.0
        self.sent_frames = 0
        self.sent_items = 0
        self.skipped_frames = 0

    def _ensure(self):
        if self._sock is not None:
            return True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((self._host, self._port))
            s.settimeout(None)
            self._sock = s
            print("[V6-BRIDGE] connected %s:%d" % (self._host, self._port))
            return True
        except Exception as exc:  # 桥不能因为网络挂掉就崩视觉
            print("[V6-BRIDGE] connect failed: %s（下次再试）" % exc)
            self._sock = None
            return False

    def _drop(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def send(self, rows, task_id=None, now=None):
        """把这一帧的 results 发出去。返回实际发出的件数。"""
        now = now if now is not None else time.monotonic()
        if now - self._last < self._interval:
            return 0
        self._last = now
        try:
            data = encode_batch_targets(
                rows, self._task_id if task_id is None else task_id)
        except Exception as exc:
            print("[V6-BRIDGE] encode failed: %s" % exc)
            return 0
        n = data[0]
        if n == 0:
            self.skipped_frames += 1
            return 0
        if not self._enable:
            print("[V6-BRIDGE] (disabled) would send %d item(s), %d bytes"
                  % (n, len(data)))
            self.sent_frames += 1
            self.sent_items += n
            return n
        if not self._ensure():
            return 0
        try:
            self._sock.sendall(data)
        except Exception as exc:
            print("[V6-BRIDGE] send failed: %s -> 重连" % exc)
            self._drop()
            return 0
        self.sent_frames += 1
        self.sent_items += n
        return n

    def close(self):
        self._drop()

    def summary(self):
        return ("[V6-BRIDGE] 累计发出 %d 帧 / %d 件（跳过空帧 %d 次）"
                % (self.sent_frames, self.sent_items, self.skipped_frames))
# <<<V6-BRIDGE>>> ================= 发送桥结束 =================


# ============ 以下为 V6 原文，未作任何修改 ============
# 🔴 2026-10-18 改动：相机从 320×320（正方形，会裁掉传感器左右 44%）改为 1280×720（16:9 全视野）。
#   · 原因：MaixPy 请求 1:1 时会从传感器 2560×1440 里裁剪出中间 1440×1440 再缩放，
#     水平方向只用 56%，导致托盘外的物料完全看不到（识别区 184.5mm < 抓取区 190×195mm）。
#   · 原调定值见 archive/相机16比9升级前-20261018/。
#   · 坐标系随之从「320 系」变为「1280×720 系」——树莓派侧 calibration_config.ini
#     的仿射参数必须同步换算，换算公式见
#     docs/reports/2026-10-18-相机视野升级与重训方案.md §6。
#   · 环境变量可覆盖，便于现场回退：FRAME_W / FRAME_H / DETECT_SIZE。
FRAME_W = int(os.environ.get("FRAME_W", "1280"))   # 原来是 FRAME_SIZE = 320（正方形）
FRAME_H = int(os.environ.get("FRAME_H", "720"))
# DETECT_SIZE 必须按「每像素毫米数」同步放大，否则 MIN_BBOX_SIDE_DET / MIN_AREA_DET_PX
# 等阈值全部失效：
#   旧：0.5766 mm/px ÷ (224/320) = 0.824 mm/px(检测缓冲)
#   新：0.2563 mm/px ÷ (400/1280) = 0.820 mm/px(检测缓冲)  ← 基本一致，阈值可沿用
DETECT_SIZE = int(os.environ.get("DETECT_SIZE", "400"))  # 原 224
TARGET_FPS = 6.0  # 最高显示节奏；计算较慢时不会强行达到该帧率。
CONFIRM_FRAMES = 2
SMOOTH_TIME = 0.22  # 秒，越大越平稳，但移动时跟随更慢。
HOLD_SECONDS = 0.30  # 短时漏检仅保留灰色 HOLD 框，不输出货格。
MAX_TRACK_GAP = 0.65
PERF_INTERVAL = 5.0
PREVIEW_JPEG_QUALITY = 70  # 仅电脑预览 JPEG 质量，原始检测图与设备屏幕不降质。
LOG_RESULTS = False  # True 时每 5 秒额外输出一行物料结果。
ROI_MARGIN = 0.01
MIN_AREA_FRACTION = 0.0015
MAX_AREA_FRACTION = 0.22
MIN_COLOR_FRACTION = 0.60   # 2026-09-23 DSH: 只靠颜色判据，贴边阴影使占比下降，放宽
# 🔴 2026-10-25：同色多件时，保留面积 ≥ 同色最大者此比例的候选。
# 旧逻辑是「每种颜色只留最大一个」，前提是校赛「一色一件」。
# 新赛规下绿/蓝/黄各有 2 件 ⇒ 旧逻辑 7 件只报 4 件。
# 取 0.30：碎屑通常 < 主件 5%，0.30 既能滤碎屑又能保住真件。
# ⚠️ 若现场发现「紧挨着的小件被吞」就往下调（如 0.20）。
SAME_COLOR_AREA_RATIO = 0.30
SHAPE_EXTENT_CENTROID = 0.65   # A'(2026-09-21) ext<此值判为"非中心对称形状"，抓取点改用形心
_REJ = {}                      # 方案0(2026-09-21) 每帧五道 continue 的拒绝计数
_REJ_TOT = {}                  # F3(2026-09-21) 进程内累计，用于事件触发打印
_REJ_C = {}                    # ②(2026-09-21) 同上，但按颜色分开：{gate: {color: n}}
# ②的理由：全局计数看不出"是哪一色在被丢"。c2_border=6 到底是 6 个红件的碎屑，
# 还是黑圆柱被整件判掉？后者要改门限，前者不用管。量级差一个决策。
# ponytail: 只加一层 {gate: {color: n}}，不加直方图/时间序列；要趋势就存日志。


def _bump(gate, color=None):
    """拒绝计数统一入口：同时记全局与按色。全局键名不变，老读法继续有效。"""
    _REJ[gate] = _REJ.get(gate, 0) + 1
    if color is not None:
        _d = _REJ_C.setdefault(gate, {})
        _d[color] = _d.get(color, 0) + 1

# M2/M3/M5(2026-09-21)：外部报告实测量化后新增的三道门 + black 更严确认。
# M2 绝对尺寸下限（det 口径；= 320 口径短边 62px / 面积 2600px²）：
#   实测依据：关掉 c2 后每帧多出的假目标短边 59px@320、面积 2258~2485px²@320，
#   而最小真件是短边 73px / 面积 3089px²。且过曝把件切成两半时残片 area=1550px²@320、
#   extent=0.5047（≈理想三角 0.5）⇒ **相对形状判据抓不到，只有绝对面积下限能抓**。
#   ⚠️ 只加下限，坚决不加上限（实测 cube 的 cyan 候选 99×94 / 8078.6px² 已超出旧"自述带"）。
MIN_BBOX_SIDE_DET = 30   # 2026-09-23: 43 会误杀窄件（实拍窄边28px@224）         # 短边下限 px(224)
MIN_AREA_DET_PX = 850.0   # 2026-09-23: 同步放宽面积下限       # 面积下限 px²(224)
# M3 饱和门：本场景正常帧的 (V>=245 & S<=25) 像素实测为 0 / 0 / 0。
#   门限 1500px@320 落在"被 c4 打掉(1793)"与"坐标还能用(1257)"之间。
MAX_SATURATED_PX = 1500
# M5 black 更严确认：夹爪/机架也是黑的，黑件要求连续 3 帧静置才确认（彩色仍 2 帧）。
BLACK_CONFIRM_FRAMES = 3
# AE/AWB 锁定开关：**默认关**。锁定后六色 HSV 阈值必须全部重标，故先留开关、现场取证后再开。
LOCK_AE_AWB = False
KERNEL = np.ones((3, 3), np.uint8)
# ④-②(2026-09-21) 机构扫掠遮罩：夹爪与 X/Y 轴黑方框**本身就是黑的**，与黑圆柱同色。
# 实测三张不同件的实拍互比：件 bbox 内帧间变化 36.9~67.3%，那两块固定黑物内 0.00~0.06%
# ⇒ 颜色/亮度/形状/面积全都分不开，唯一与光照无关的判据是"动过没有"。
# 为什么非做不可：现在挡住幻影的余量只有 3px / 4.6%（短边 59 vs M2 下限 62、
# 面积 2470 vs 2600），而幻影自身帧间抖动 ±10% ⇒ 换个光照它就会通过 M2 变成"像件"的目标。
# 由 make_gripper_mask.py 一次性标定产出（那一步由人手动移动机构，本文件绝不自主动）。
# ⚠️ 文件不存在 ⇒ 这道门**完全不生效**，行为与今天逐字节相同。
GRIPPER_MASK_PATH = "/root/forensic/gripper_mask.png"
GRIPPER_MASK_OVERLAP_MAX = 0.0   # 黑候选 bbox 内允许落在遮罩里的比例；0 = 必须完全在遮罩外

# ═══════════════════════════════════════════════════════════════════════════
# 🔴 2026-10-25 重标定：窗口按 MaixCAM 实拍照实测值重写
#
# 测量方法：_pi_tools/measure_tray_hsv.py，在实拍 1280x720 托盘照片上
#          对每个物块中心 ±18px 采样，统计 H/S/V。
# 实测值（灯开、AE/AWB 已收敛）：
#   绿  H 69~75   S 144~207  V 160~193   （正方体 + 圆柱）
#   蓝  H 107~112 S 227~255  V 134~173   （长方体 + 五棱柱侧放）
#   红  H 171~173 S 223~255  V 145~168   （四棱锥）
#   黄  H 20~22   S 152~167  V 209~234   （五棱柱 + 长方体）
#
# 🔴 修掉的两个致命错误（旧窗口的锅）：
#   1) 红：旧窗口是 H[0,2] + H[173,179]，实测 171~173 ⇒ **171-172 落在缝隙里**，
#      红四棱锥几乎完全漏检。新窗口改 H[167,177] 覆盖实测。
#   2) 黄：旧 yellow 窗口 H[24,35]，而实测黄是 H 20~22 ⇒ **落进 orange 的 H[3,23]**，
#      所有黄色物料被误判成"橙色"→"圆柱"。新 yellow 改 H[16,26]。
#      orange 缩到 H[3,14]，不再抢黄色。
#
# 另外按新赛规（5 色 × 6 形状解耦）：
#   · 删除 cyan（新赛规无青色）
#   · 保留 black 但**只用于机构剔除**（夹爪/轴是黑的），不作为物料颜色
#   · **白色物料窗口待后续添加**（需 V≥175 且 S≤55，与深灰托盘区分）
#
# ⚠️ 本文件只用颜色输出「颜色」，**形状不再由颜色决定**（同色多形状，
#    例如绿既是正方体又是圆柱）—— 形状交给 YOLO / 几何判定。
#    但为了让下游链路不炸，COLOR_TO_MATERIAL 暂时保留旧映射。
# ═══════════════════════════════════════════════════════════════════════════
COLOR_RANGES = {
    # 🔴 核心修正：**只改 H 区间**，S/V 下界一律回到原来的宽松值。
    #
    # 为什么不能收紧 S/V：判定链里有一道 MIN_COLOR_FRACTION = 0.60，
    # 要求「bbox 内颜色像素占比 ≥ 60%」。物块边缘/阴影/反光的 S/V 明显低于
    # 中心采样值 ⇒ 把 S/V 下界抬高会让 mask 变小、占比跌破 60% ⇒ **整件被丢**。
    # 实测教训（2026-10-25）：S 下界一度抬到 110~180，结果 7 件只检出 1 件。
    # H 才是区分颜色的关键量；S/V 只用来排除「灰色/过暗」的像素。
    #
    # 红：实测 H 171~173，旧窗口的 0~2 与 173~179 中间有缝 ⇒ 合并成一段
    "red": [((167, 95, 35), (177, 255, 255))],
    # 黄：实测 H 20~22（旧窗口 24~35 完全够不着）
    "yellow": [((16, 95, 45), (26, 255, 255))],
    # 橙：托盘上没有橙色物料；缩到 H[3,14]，避免抢黄色
    "orange": [((3, 95, 45), (14, 255, 255))],
    # 绿：实测 H 69~75
    "green": [((62, 95, 35), (82, 255, 255))],
    # 蓝：实测 H 107~112
    "blue": [((100, 95, 30), (122, 255, 255))],
    # ⚠️ cyan：新赛规无青色物料，但 **bin 编号 1~6 不能动**（Pi 侧 [BoxMap] 依赖它）。
    #    给一个 H=255 的**不可能窗口**（OpenCV H 最大 179）⇒ 永不匹配，
    #    既保证两个字典键集一致（不会 KeyError），又让 cyan 实际失效。
    "cyan": [((255, 255, 255), (255, 255, 255))],
    # 黑：不作为物料颜色，只留给机构剔除逻辑（夹爪/轴）用
    "black": [((0, 0, 0), (179, 150, 50))],
    # 🔴 2026-10-26 新增：白色窗口（省赛新要求）
    #    初值：V≥175（明亮）且 S≤55（低饱和度 = 接近灰白）
    #    ⚠️ 白托盘也是白的 → 容易误检。靠以下机制区分：
    #       1. c1_area：托盘面积超 MAX_AREA_FRACTION=0.22，先被丢
    #       2. c4_color_frac≥0.60：物料中心颜色占比高，托盘边缘有阴影
    #       3. 形状判据：物料是 3D 几何体（轮廓复杂），托盘是平面矩形
    #    TODO: 现场标定后微调（用 _pi_tools/measure_tray_hsv.py 测实拍值）
    "white": [((0, 0, 175), (179, 55, 255))],
}
COLOR_TO_MATERIAL = {
    "cyan": ("cube", 1), "green": ("cube", 2),
    "red": ("triangular_prism", 3), "blue": ("triangular_prism", 4),
    "black": ("cylinder", 5), "orange": ("cylinder", 6),
    # 🔴 2026-10-25 修复：yellow **原本完全不在这张表里** ⇒ L394 的
    #    `for color in COLOR_TO_MATERIAL` 从来不扫描黄色 ⇒ 黄色物料完全消失。
    #    实测托盘上有 2 件黄色（五棱柱 + 长方体），必须加进来。
    #    bin 暂用 6（orange 的窗口已缩到 H[3,14]，实际不会命中，不会冲突）。
    #    shape 用 "unknown"：新赛规下颜色不能定形状，形状交给 YOLO/几何。
    "yellow": ("unknown", 6),
    # 🔴 2026-10-26 新增：白色（省赛新要求）
    #    旧路径（USE_GEOMETRY_SHAPE=False）占位用，新路径不走这里。
    #    shape 用 "unknown"，bin 暂用 6（与 yellow/orange 不冲突）。
    "white": ("unknown", 6),
}
DISPLAY_SHAPE = {"cube": "cube", "cylinder": "cylinder",
                 "triangular_prism": "tri-prism", "unknown": "unknown"}


def _mark(_tr, gate=None, **extra):
    """⑤(2026-09-21) 取证用：记下"这个轮廓被哪道闸丢了"以及闸的输入量。

    trace=None 时是纯空操作，线上零开销。存在的理由：旧取证脚本抄了一份 analyze()，
    抄本必然落后（今天已落后 4 次改动），于是在现场产出一份"看起来很像、其实描述的是
    不存在的闸"的报告。让生产函数自己吐中间量，抄本就不需要了，也就不会再漂移。
    """
    if _tr is not None:
        if gate:
            _tr["gate"] = gate
        _tr.update(extra)


def analyze(pixels, input_rgb=False, detect_size=None, trace=None,
            gripper_mask=None):
    """六色分别找区域，避免阴影将异色物料连成一个目标。只读输入。

    trace: 传一个 dict 就顺带记下每道闸的中间量（只为取证）。默认 None ⇒
    行为逐字节不变、判定路径零开销。
    """
    _REJ.clear()
    _REJ_C.clear()
    _REJ.update(c1_area=0, c2_border=0, c3_aspect_extent=0,
                c4_color_frac=0, c5_black_core=0, c6_black_mutex=0,
                c7_min_size=0, c8_saturated=0, c9_gripper_mask=0)
    original_h, original_w = pixels.shape[:2]
    limit = DETECT_SIZE if detect_size is None else detect_size
    if limit < 32:
        raise ValueError("detect_size must be at least 32")
    scale = min(1.0, float(limit) / max(original_w, original_h))
    if scale < 1.0:
        # 最近邻不混合红橙边缘色相；没有使用跳帧或复用上一帧结果。
        pixels = cv2.resize(pixels, (max(1, round(original_w * scale)),
                                     max(1, round(original_h * scale))),
                            interpolation=cv2.INTER_NEAREST)
    height, width = pixels.shape[:2]
    sx, sy = original_w / width, original_h / height
    x0, y0 = int(width * ROI_MARGIN), int(height * ROI_MARGIN)
    x1, y1 = width - x0, height - y0
    hsv = cv2.cvtColor(pixels[y0:y1, x0:x1],
                       cv2.COLOR_RGB2HSV if input_rgb else cv2.COLOR_BGR2HSV)
    min_area = MIN_AREA_FRACTION * width * height
    max_area = MAX_AREA_FRACTION * width * height
    # M3(2026-09-21) 饱和门：过曝会让 S→0，六个彩窗**同时**失配 ⇒ 整件消失；
    # 更阴险的是"把掩膜切成两半、全闸放行、抓取点偏 8.7mm"（实测 prism_tri r=20）。
    # 本场景正常帧的 (V>=245 & S<=25) 像素实测为 0/0/0，故这道门几乎零误伤。
    _sat = int(np.count_nonzero((hsv[:, :, 2] >= 245) & (hsv[:, :, 1] <= 25)))
    if trace is not None:
        # ⑤ metadata：取证脚本原本要自己复现 resize/ROI/闸口径才能算这些数，
        # 复现就是"第二份真相"。这里直接给它唯一的真相。
        trace.update(det=(width, height), sx=sx, sy=sy, roi_det=(x0, y0, x1, y1),
                     roi_320=(round(x0 * sx), round(y0 * sy),
                              round(x1 * sx), round(y1 * sy)),
                     min_area_det=min_area, max_area_det=max_area,
                     min_area_320=min_area * sx * sy, max_area_320=max_area * sx * sy,
                     sat=_sat, rows=[])
    # ④-② 遮罩与 hsv 同口径：先按同一个 scale 缩到 det 尺寸，再裁到同一个 ROI，
    # 于是黑候选的 (x,y,w,h) 可以直接索引它，不需要第二套坐标换算。
    _gm = None
    if gripper_mask is not None:
        _gm = gripper_mask
        if scale < 1.0:
            _gm = cv2.resize(_gm, (width, height), interpolation=cv2.INTER_NEAREST)
        _gm = _gm[y0:y1, x0:x1] > 0
    if _sat >= MAX_SATURATED_PX:
        _REJ["c8_saturated"] = _sat
        for _k in _REJ:
            _REJ_TOT[_k] = _REJ_TOT.get(_k, 0) + _REJ[_k]
        print("V6 SATURATED frame=%d sat=%d -> 本帧不报目标" % (
            getattr(analyze, "_frames", 0) + 1, _sat))
        analyze._frames = getattr(analyze, "_frames", 0) + 1
        return [], (round(x0 * sx), round(y0 * sy), round(x1 * sx), round(y1 * sy))
    results = []
    for color in COLOR_TO_MATERIAL:
        ranges = COLOR_RANGES[color]
        mask = cv2.inRange(hsv, ranges[0][0], ranges[0][1])
        for low, high in ranges[1:]:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, low, high))
        # 每种颜色独立去噪和补小洞，不再把所有暗色和彩色区域连在一起。
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL)
        contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
        candidates = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            # ⑤ 取证：boundingRect 提到面积闸之前。纯函数、不改任何判定，但让被
            # 面积闸丢掉的轮廓也能报 bbox（旧抄本正是靠这一点才看得见 c1 的现场）。
            x, y, w, h = cv2.boundingRect(contour)
            _tr = None
            if trace is not None:
                _tr = {"color": color, "area_det": area, "bbox_det": (x, y, w, h),
                       "gate": None}
                trace["rows"].append(_tr)
            if not min_area <= area <= max_area:
                _bump("c1_area", color)
                _mark(_tr, "c1_area")
                continue
            # 接触 ROI 的区域往往是托盘外背景；不画满屏 CHECK 大框。
            # C2 改判据(2026-09-21)：从「贴任意 1 条 ROI 边就丢」改成「贴 >=2 条才丢」。
            # 实测依据：杆子/机架的深色带贴 2~3 条边（(9,253,61,59) 贴 2 条；
            # (271,9,40,303) 贴 3 条），而真实件只贴 1 条边 —— 用户现场目击：
            # 蓝正方体 4/5 在识别框内，却被现行 c2 整件丢掉。
            # 代价：贴 1 条边时只能按可见部分算中心，会偏向可见一侧
            # （4/5 可见 ≈ 偏 4mm，仍在 5mm 预算内）；可见更少的由 M2 面积下限兜底。
            # ⚠️ 根因未治：ROI 只内缩 3%=4.37mm，比项目自身 5mm 误差预算还小，
            #    c2 一直是在替一个"选得太小的 ROI"兜底。正解是重定取景/托盘位置。
            _edge = ((x <= 1) + (y <= 1) + (x + w >= hsv.shape[1] - 1)
                     + (y + h >= hsv.shape[0] - 1))
            # ⑤ 无条件记下贴边数（不只记被丢的）：取证脚本就不必自己再算一遍 c2 判据。
            _mark(_tr, edge=_edge)
            if _edge >= 3:   # 2026-09-23 DSH: 贴>=2边就丢 会误杀贴边件（用户实测）
                _bump("c2_border", color)
                _mark(_tr, "c2_border")
                continue
            # M2(2026-09-21) 绝对尺寸下限：c2 之后、c3 之前。
            # 它同时是"贴 ROI 边的静物黑块"的兜底与"过曝半件"的唯一解药
            # （半件 extent≈0.5 与理想三角无异，只有绝对面积能识别）。
            if min(w, h) < MIN_BBOX_SIDE_DET or area < MIN_AREA_DET_PX:
                _bump("c7_min_size", color)
                _mark(_tr, "c7_min_size")
                continue
            # ④-②(2026-09-21) c9 机构扫掠遮罩：**只对 black 生效**。
            # 夹爪与 X/Y 轴黑方框会动，件放好后不动 —— 差分信号差 3 个数量级。
            # 遮罩为 None（没标定过）时整段跳过 ⇒ 零行为变化。
            if _gm is not None and color == "black":
                _ov = float(_gm[y:y + h, x:x + w].mean()) if (w and h) else 0.0
                _mark(_tr, gripper_overlap=_ov)
                if _ov > GRIPPER_MASK_OVERLAP_MAX:
                    _bump("c9_gripper_mask", color)
                    _mark(_tr, "c9_gripper_mask")
                    continue
            if min(w, h) / max(w, h) < 0.28 or area / (w*h) < 0.35:
                _bump("c3_aspect_extent", color)
                _mark(_tr, "c3_aspect_extent")
                continue  # 排除细长背景条和极稀疏噪声，不据此确定物料形状。
            inside = np.zeros((h, w), np.uint8)
            local = contour - np.array([[[x, y]]], dtype=contour.dtype)
            cv2.drawContours(inside, [local], -1, 255, -1)
            inside = cv2.erode(inside, KERNEL, borderType=cv2.BORDER_CONSTANT, borderValue=0)
            count = cv2.countNonZero(inside)
            crop = hsv[y:y+h, x:x+w]
            matching = cv2.inRange(crop, ranges[0][0], ranges[0][1])
            for low, high in ranges[1:]:
                matching = cv2.bitwise_or(matching, cv2.inRange(crop, low, high))
            votes = cv2.countNonZero(cv2.bitwise_and(matching, inside))
            fraction = votes/count if count else 0.0
            _mark(_tr, color_fraction=fraction)
            if fraction < MIN_COLOR_FRACTION:
                _bump("c4_color_frac", color)
                _mark(_tr, "c4_color_frac")
                continue
            if color == "black":
                # 真黑物料应有足够深色核心，浅灰投影不应变成黑色圆柱。
                core = cv2.inRange(crop, (0, 0, 0), (179, 150, 38))
                # ⑤ 把算好的比值存下来再判：阈值与判定逐字节不变。
                _cr = (cv2.countNonZero(cv2.bitwise_and(core, inside)) / count
                       if count else 0.0)
                _mark(_tr, black_core=_cr)
                if not count or _cr < 0.30:
                    _bump("c5_black_core", color)
                    _mark(_tr, "c5_black_core")
                    continue
            left, top = round((x+x0)*sx), round((y+y0)*sy)
            right = min(original_w, round((x+x0+w)*sx))
            bottom = min(original_h, round((y+y0+h)*sy))
            # ────────────────────────────────────────────────────────────
            # 2026-10-23：形状来源在这里分叉
            #
            # 旧路径（USE_GEOMETRY_SHAPE=False，默认）：
            #     颜色 → COLOR_TO_MATERIAL 硬编码表 → (形状, 盒号)
            #     ⚠️ 这是校赛"颜色唯一确定货物"的做法，新赛规下失效。
            #
            # 新路径（USE_GEOMETRY_SHAPE=True）：
            #     轮廓几何 → 形状 → SHAPE_TO_BOX → 盒号
            #     颜色只留在候选字典里做日志/取证，不参与决策。
            #
            # 歧义/未知（圆类 = 圆柱或圆锥未定；或判不出）时**直接跳过该候选**：
            # 不给 bin ⇒ 本轮不发它。这是刻意的 —— 赛规图4 规定混装任何两类
            # 计 0 分，宁可漏一件（最多少 2 分）也不能装错（毁掉整盒）。
            # 调度层应把它们留到最后处理（用户 2026-10-23 裁决）。
            # ────────────────────────────────────────────────────────────
            if USE_GEOMETRY_SHAPE and _shape_lite is not None:
                _gs = _shape_lite.classify_contour_shape(contour)
                if not _gs.is_decided:
                    _bump("c10_shape_undecided", color)
                    _mark(_tr, "c10_shape_undecided",
                          shape_verdict=_gs.shape, shape_rule=_gs.evidence.get("rule"))
                    continue
                shape = _gs.shape
                bin_id = _shape_lite.shape_to_box(shape)
                if bin_id is None:            # 理论上 is_decided 时不会是 None，双保险
                    _bump("c11_shape_no_box", color)
                    _mark(_tr, "c11_shape_no_box", shape_verdict=shape)
                    continue
                _src = "geometry"
                _mark(_tr, shape_verdict=shape,
                      shape_rule=_gs.evidence.get("rule"),
                      rect_fill=_gs.evidence.get("rect_fill"),
                      circularity=_gs.evidence.get("circularity"),
                      n_vertices=_gs.evidence.get("n_vertices"))
            else:
                shape, bin_id = COLOR_TO_MATERIAL[color]
                _src = "color"
            # A'(2026-09-21)：只在"测出不是中心对称形状"时才用形心当抓取点。
            # 三角形 ext∈[0.464,0.500]、圆盘 0.785、正方形 1.000 ⇒ 条件天然只命中三角形；
            # 对称形状走原 bbox 中心路径，取值逐字节不变。
            _ext = area / float(w * h) if w and h else 1.0
            if _ext < SHAPE_EXTENT_CENTROID:
                _m = cv2.moments(contour)
                if _m["m00"] > 0:
                    cxl, cyl = _m["m10"] / _m["m00"], _m["m01"] / _m["m00"]
                else:
                    cxl, cyl = x + w / 2.0, y + h / 2.0
            else:
                cxl, cyl = x + w / 2.0, y + h / 2.0
            candidates.append({"color": color, "shape": shape, "bin": bin_id,
                               # 2026-10-23：来源随开关走，便于日志区分走了哪条路径。
                               # 旧路径保持 "color"/"color_mapping" 原值（逐字节不变）。
                               "classification_source": _src,
                               "reason": ("geometry_mapping" if _src == "geometry"
                                          else "color_mapping"),
                               "color_fraction": fraction, "area": area*sx*sy,
                               "bbox": (left, top, right-left, bottom-top),
                               # F1(2026-09-21)：中心必须**存进候选**，否则上面算的形心当场被丢掉。
                               # 口径与 bbox 一致：都乘回 320 系并加上 ROI 偏移 (x0,y0)。
                               "center": (round((cxl + x0) * sx), round((cyl + y0) * sy)),
                               "clipped": False})
        # 🔴 2026-10-25 修改：旧逻辑是「每种颜色只保留面积最大的一个候选」，
        #    前提是校赛「一种颜色只对应一个物料」。
        #    新赛规下**同色多件**（实测托盘：绿=正方体+圆柱、蓝=长方体+五棱柱、
        #    黄=五棱柱+长方体）⇒ 旧逻辑会每色只报 1 件，7 件只报出 4 件。
        #
        #    改为：保留所有面积 ≥ 同色最大者 30% 的候选。
        #    · 30% 足以滤掉碎屑/反光小块（实测碎片面积通常 < 主件的 5%）
        #    · 又能保住真正的第二个同色件
        #    ⚠️ 这个阈值是启发式，现场若发现"紧挨着的小件被吞"就往下调。
        if candidates:
            _max_area = max(r["area"] for r in candidates)
            _keep_min = _max_area * SAME_COLOR_AREA_RATIO
            _kept = [r for r in candidates if r["area"] >= _keep_min]
            if _kept:
                results.extend(_kept)
    results.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))
    # C(2026-09-21)：black 与彩色候选空间互斥。
    # black 窗口 :191 横跨全部色相、与彩色窗在 S∈[95,150] 重叠 ⇒ 同一个物体可能
    # 同时产出 bin4(blue) 与 bin5(black)（实测 HSV(120,120,34) 双发）。这里丢掉与
    # 彩色候选 bbox 重叠、或中心距 < 0.5*max(w,h) 的 black 候选。
    # 系数取 0.5 而非 0.8：幻影双发的两候选中心几乎重合，0.5 一样拦得住，
    # 却更不容易误丢"紧挨着彩色件"的真黑圆柱。
    # ponytail: 启发式上限，只做空间互斥，不动 :184-192 的色阈值。
    _colored = [r for r in results if r["color"] != "black"]
    if _colored:
        _kept = []
        for _row in results:
            if _row["color"] != "black":
                _kept.append(_row)
                continue
            _l, _t, _w, _h = _row["bbox"]
            _rc = _row.get("center") or (_l + _w // 2, _t + _h // 2)
            _drop = False
            for _o in _colored:
                _ol, _ot, _ow, _oh = _o["bbox"]
                _oc = _o.get("center") or (_ol + _ow // 2, _ot + _oh // 2)
                _ix = max(0, min(_l + _w, _ol + _ow) - max(_l, _ol))
                _iy = max(0, min(_t + _h, _ot + _oh) - max(_t, _ot))
                # F4(2026-09-21)：判据从"1 像素相交 or 中心近"收紧为 **IoU>=0.6**。
                # 实测依据：幻影是"同一批像素同时进两个窗"，IoU≈1，稳过；
                # 而画面右缘那堵墙(blue#0 × black#5)的 IoU 只有 0.19 ⇒ 不再误杀；
                # 真黑圆柱与彩色件相邻时 IoU≈0 ⇒ 保住。旧写法每边有 2~4mm 的误伤带。
                _inter = _ix * _iy
                _union = _w * _h + _ow * _oh - _inter
                _iou = (_inter / _union) if _union > 0 else 0.0
                if _iou >= 0.6:
                    _drop = True
                    # ②(2026-09-21)：c6 之前**从来没被计数过**（init 里有键、无人自增），
                    # 于是"black 被 C 段悄悄丢掉"在日志里完全不可见。补上——这条丢的
                    # 恰好是真黑圆柱，是现场最需要看见的一条。
                    _bump("c6_black_mutex", _row["color"])
                    break
            if not _drop:
                _kept.append(_row)
        results = _kept
    # F3(2026-09-21)：原来"每 60 帧挑第 1 帧打印"，导致 59/60 帧的读数全丢。
    # 改为**累计 + 事件触发**：只有"本帧一个候选都没留下"或"本帧有任何一闸拒绝"时
    # 才打印，既不再丢信息，正常帧也不刷屏。
    for _k in _REJ:
        _REJ_TOT[_k] = _REJ_TOT.get(_k, 0) + _REJ[_k]
    analyze._frames = getattr(analyze, "_frames", 0) + 1
    if (not results) or any(_REJ.values()):
        # ②(2026-09-21) 追加 bycolor 段：只列非零项，正常帧通常 1~3 项，不刷屏。
        _pc = " ".join("%s:%s=%d" % (g, c, n)
                       for g in sorted(_REJ_C) for c, n in sorted(_REJ_C[g].items()) if n)
        print("V6 REJECT frame=%d kept=%d | frame[%s] | total[%s] | bycolor[%s]"
              % (analyze._frames, len(results),
                 " ".join("%s=%d" % (k, _REJ[k]) for k in sorted(_REJ)),
                 " ".join("%s=%d" % (k, _REJ_TOT[k]) for k in sorted(_REJ_TOT)),
                 _pc or "-"))
    return results, (round(x0*sx), round(y0*sy), round(x1*sx), round(y1*sy))


class StableTargets:
    """跨帧稳定确认 + 时间平滑 + 短时漏检保留灰框。

    🔴 2026-10-25：从「每色一件」升级为「**同色可多件**」。
       旧实现 `self.tracks` 是 `dict[color] -> track`，天然只能记一件/色。
       新实现改为 `list[track]`，靠**空间距离**区分同色的不同物件。
       （新赛规下同色多件是常态：实测托盘绿×2、蓝×2、黄×2）
    """
    def __init__(self):
        # list，每个元素是一条轨迹：{color, box, hits, confirmed, last_seen, row, center}
        self.tracks = []

    def update(self, detections, now):
        """把本帧检测并入跨帧轨迹，返回已确认的目标。

        🔴 2026-10-25 重写：**旧实现按「颜色」建轨迹（`self.tracks[color]`），
           假设一色只有一件**。新赛规下同色多件（实测托盘：绿=正方体+圆柱、
           蓝=长方体+五棱柱、黄=五棱柱+长方体）⇒ 同色两件会抢同一个轨迹槽，
           距离一超阈值就 reset，永远凑不满 CONFIRM_FRAMES ⇒ **整件发不出去**。
           实测现象：门限后 kept=7，线上只发 1 件。

           新实现：`self.tracks` 改为**列表**，每帧对每个检测找「同色且位置最近」
           的轨迹接上；找不到就新建。这样同色多件各自有独立轨迹。
           位置匹配用中心距 < max(30px, 0.9×旧框长边)，与旧 reset 判据保持一致。
        """
        # ── 1) 逐检测匹配已有轨迹 ──────────────────────────────────────
        matched = set()          # 已匹配的 track 索引，防止两检测抢同一轨迹
        for row in detections:
            color = row["color"]
            box = np.array(row["bbox"], dtype=float)
            bc = box[:2] + box[2:] / 2.0

            # 找同色、未匹配、中心最近且足够近的轨迹
            best_i, best_d = -1, None
            for i, tr in enumerate(self.tracks):
                if i in matched or tr["color"] != color:
                    continue
                ob = tr["box"]
                oc = ob[:2] + ob[2:] / 2.0
                d = float(np.linalg.norm(bc - oc))
                limit = max(30.0, 0.9 * max(ob[2], ob[3]))
                if d <= limit and (best_d is None or d < best_d):
                    best_i, best_d = i, d

            _c = np.array(row.get("center") or (
                row["bbox"][0] + row["bbox"][2] / 2.0,
                row["bbox"][1] + row["bbox"][3] / 2.0), dtype=float)

            if best_i >= 0:
                tr = self.tracks[best_i]
                matched.add(best_i)
                dt = max(0.0, now - tr["last_seen"])
                alpha = 1.0 - np.exp(-dt / SMOOTH_TIME)
                tr["box"] += alpha * (box - tr["box"])
                if tr.get("center") is None:
                    tr["center"] = _c
                else:
                    tr["center"] += alpha * (_c - tr["center"])
                tr["hits"] += 1
                tr["last_seen"], tr["row"] = now, row
            else:
                # 新轨迹（第一帧 hits=0，下一帧才 +1）
                self.tracks.append({
                    "color": color, "box": box, "hits": 0,
                    "confirmed": False, "last_seen": now,
                    "row": row, "center": _c,
                })
                self.tracks[-1]["hits"] = 1
                matched.add(len(self.tracks) - 1)

        # ── 2) 更新确认状态 ────────────────────────────────────────────
        for i, tr in enumerate(self.tracks):
            # 黑件要求连续 3 帧静置（夹爪/机架也是黑的，要更强证据）
            _need = BLACK_CONFIRM_FRAMES if tr["color"] == "black" else CONFIRM_FRAMES
            if tr["hits"] >= _need:
                tr["confirmed"] = True
            if i not in matched:
                # 本帧没匹配上：hits 归零。
                # 🔴 2026-10-26 修正：这里必须用 **or**，不是 and。
                #   原实现（按颜色建轨迹时代）是：
                #       if age > HOLD_SECONDS or not confirmed: del tracks[color]
                #   即「超时 **或** 没确认过」都删。
                #   我第一版误写成 and ⇒ 已确认的轨道**永远不会被删**，
                #   于是它一直占着槽位、导致 test_40 的"超 HOLD 后必须消失"失败。
                tr["hits"] = 0
                if (now - tr["last_seen"]) > HOLD_SECONDS or not tr["confirmed"]:
                    tr["_dead"] = True

        self.tracks = [t for t in self.tracks if not t.get("_dead")]

        # ── 3) 输出已确认轨迹 ──────────────────────────────────────────
        results = []
        for tr in self.tracks:
            if not tr["confirmed"]:
                continue
            row = dict(tr["row"])
            row["bbox"] = tuple(int(round(v)) for v in tr["box"])
            if tr.get("center") is not None:
                row["center"] = tuple(int(round(v)) for v in tr["center"])
            stale = tr["hits"] == 0
            row["stale"] = stale
            if stale:
                row["bin"], row["classification_source"], row["reason"] = (
                    None, "none", "short_hold")
            results.append(row)
        results.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))
        return results


def render_rgb(rgb, results, roi, fps=0.0):
    """小标签置于物料框内；顶部一行图例，避免长文字互相穿插。"""
    x0, y0, x1, y1 = roi
    cv2.rectangle(rgb, (x0, y0), (x1-1, y1-1), (220, 220, 0), 1)
    for r in results:
        held = r.get("stale", False)
        ink = (150, 150, 150) if held else (0, 220, 0)
        x, y, w, h = r["bbox"]
        cv2.rectangle(rgb, (x, y), (x+w-1, y+h-1), ink, 1)
        label = "HOLD" if held else "%d %s" % (r["bin"], r["color"])
        tx = max(2, min(x+2, rgb.shape[1]-75))
        ty = max(48, min(y+12, rgb.shape[0]-3))
        cv2.putText(rgb, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 2)
        cv2.putText(rgb, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.35, ink, 1)
    cv2.rectangle(rgb, (0, 0), (rgb.shape[1]-1, 34), (0, 0, 0), -1)
    cv2.putText(rgb, "V6 STABLE  FPS %.1f" % fps, (8, 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220, 220, 0), 1)
    cv2.putText(rgb, "1/2 cube  3/4 prism  5/6 cylinder", (8, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.32, (220, 220, 220), 1)


def main():
    from maix import app, camera, display, image

    cv2.setNumThreads(1)
    print("V6 STABLE + BRIDGE: 颜色定形状；显示=%dx%d，检测=%d；物料分开放且完整位于黄框内。"
          % (FRAME_W, FRAME_H, DETECT_SIZE))
    if hasattr(display, "set_trans_image_quality"):
        display.set_trans_image_quality(PREVIEW_JPEG_QUALITY)
    cam = camera.Camera(FRAME_W, FRAME_H, image.Format.FMT_RGB888)
    # AE/AWB 锁定（2026-09-21，API 真名已在设备上实测确认，MaixPy 4.12.5）：
    #   camera.AeMode/AwbMode members = [Invalid, Auto, Manual]
    #   Camera.exposure(us) / gain / iso / luma(0..100) / exp_mode(AeMode) [deprecated]
    #   Camera.set_wb_gain(List[float])  ← 文档原话"disable auto white balance"
    # 默认关（LOCK_AE_AWB=False）：**锁定后六色 HSV 阈值必须全部重标**，
    # 必须先在现场正常光照下读一次基线值再写死。
    try:
        _wb = list(cam.set_wb_gain())
        print("V6 AE/AWB baseline: exp_mode=%s exposure=%s gain=%s iso=%s luma=%s wb_gain=%s"
              % (cam.exp_mode(), cam.exposure(), cam.gain(), cam.iso(), cam.luma(), _wb))
        if LOCK_AE_AWB:
            cam.exp_mode(camera.AeMode.Manual)
            cam.awb_mode(camera.AwbMode.Manual)
            # 实测(2026-09-21 现场)：AWB 处于 Auto 时 set_wb_gain() 读回 [0,0,0,0]，
            # 必须先切手动再读，否则"读一次再写死"会把全 0 写进去。
            cam.set_awb(0)
            _wb2 = list(cam.set_wb_gain())
            if _wb2 and any(_wb2):
                cam.set_wb_gain(_wb2)
            print("V6 AE/AWB LOCKED: exposure=%s gain=%s wb_gain=%s"
                  % (cam.exposure(), cam.gain(), cam.set_wb_gain()))
    except Exception as _exc:
        print("V6 AE/AWB lock unavailable: %s（继续用自动曝光）" % _exc)
    # ④-② 机构扫掠遮罩：只在文件存在时启用。**绝不在生产循环里自动标定/动机构。**
    gripper_mask = None
    try:
        if os.path.exists(GRIPPER_MASK_PATH):
            gripper_mask = cv2.imread(GRIPPER_MASK_PATH, cv2.IMREAD_GRAYSCALE)
            if gripper_mask is None:
                print("V6 GRIPPER MASK 读不了：%s ⇒ c9 门不生效" % GRIPPER_MASK_PATH)
            else:
                _n = int(cv2.countNonZero(gripper_mask))
                print("V6 GRIPPER MASK 已载入 %s  白像素 %d (%.2f%%)"
                      % (GRIPPER_MASK_PATH, _n, 100.0 * _n / gripper_mask.size))
        else:
            print("V6 GRIPPER MASK 不存在（%s）⇒ c9 门不生效；"
                  "标定见 make_gripper_mask.py" % GRIPPER_MASK_PATH)
    except Exception as _exc:
        print("V6 GRIPPER MASK 载入失败：%s ⇒ c9 门不生效" % _exc)
    try:
        disp = display.Display()
        tracker = StableTargets()
        sender = BatchSender()          # <<<V6-BRIDGE>>> 新增
        print("[V6-BRIDGE] 目标 %s:%d  enable=%s" % (GATEWAY_HOST, GATEWAY_PORT, ENABLE_NETWORK))
        started = time.monotonic()
        frames, fps = 0, 0.0
        totals = [0.0] * 6
        work_max = 0.0
        while not app.need_exit():
            t0 = time.monotonic()
            frame = cam.read()
            if frame is None:
                continue
            t1 = time.monotonic()
            # RGB 共享视图：frame 必须保持存活到绘制和 disp.show 完成。
            rgb = image.image2cv(frame, ensure_bgr=False, copy=False)
            t2 = time.monotonic()
            detections, roi = analyze(rgb, input_rgb=True,
                                      gripper_mask=gripper_mask)
            results = tracker.update(detections, time.monotonic())
            sender.send(results)        # <<<V6-BRIDGE>>> 新增
            t3 = time.monotonic()
            render_rgb(rgb, results, roi, fps)
            t4 = time.monotonic()
            # rgb 的原地绘制已写入 frame，直接显示，无需 cv2image 回转换。
            disp.show(frame)
            del rgb  # 在下一次读取/释放原帧前释放借用视图。
            work_done = time.monotonic()
            # 限制最高帧率，不通过积累旧帧/旧框来制造“稳定”。
            wait = 1.0/TARGET_FPS - (work_done-t0)
            if wait > 0:
                time.sleep(wait)
            now = time.monotonic()
            frames += 1
            for i, elapsed in enumerate((t1-t0, t2-t1, t3-t2, t4-t3, work_done-t4, now-work_done)):
                totals[i] += elapsed
            work_max = max(work_max, work_done-t0)
            if now-started >= PERF_INTERVAL:
                fps = frames / (now-started)
                print("V6 PERF FPS=%.1f read=%.1fms view=%.1fms detect=%.1fms draw=%.1fms display=%.1fms pace=%.1fms work_max=%.1fms" %
                      ((fps,) + tuple(v*1000.0/frames for v in totals) + (work_max*1000.0,)))
                print(sender.summary())   # <<<V6-BRIDGE>>> 新增：跟着性能行一起报发送量
                if LOG_RESULTS:
                    print("RESULT " + (" | ".join("%s %s BIN=%s" % (r["color"], r["shape"], r["bin"])
                                                for r in results) or "empty"))
                started, frames, work_max = now, 0, 0.0
                totals = [0.0] * 6
    finally:
        sender.close()                  # <<<V6-BRIDGE>>> 新增
        cam.close()


if __name__ == "__main__":
    main()
