#!/usr/bin/env python3
"""智能分拣装置 · 总控面板（核心 4 区）

    python control_panel.py            # 开面板
    python control_panel.py --selftest # 只跑离线自检（不连设备、不开窗）

四个区
    1 实时监控  MaixCAM 检测流 + **推理停滞告警**（PDF §04：不能只看心跳）
    2 参数      conf/iou 实时下发；调度/网络/调试项写进 sorting_config.ini
    3 对应表    (颜色, 形状) -> 货格号；六个货格的落点坐标
    4 烧录      写文件 / 下发 MaixCAM / 生成树莓派部署命令 / 导出 Python 片段

为什么要这个面板
    `BoxAssignment`（对应表）与 `DropTable`（六盒坐标）在整个工作区里
    **只在测试里被构造过，没有任何数据文件、没有生产消费方**。
    这个面板给它们一个能编辑、能校验、能导出的家。

写入哪些文件
    只写 `sorting_config.ini`，且**只动 `[BoxMap]` / `[DropPoints]` 两节**，
    其余文字（含注释）逐字节保留 —— configparser 会吞掉注释，所以这里是文本级替换。

对应表语义（与代码同源，勿手改本文件的词表）
    BoxAssignment.mapping : (color_id, shape_id) -> box_id  (box_id 取 1..6)
    color_id = DEFAULT_COLOR_VOCABULARY 的下标（视觉/src/sorting_vision/sort_plan.py）
    shape_id = YOLO 类别号（workspace_label/classes.txt）
    DropPoint            : (x_0_1mm, y_0_1mm)，原点=装置中心，域 ±1450 = ±145.0mm

依赖 PyQt5：  py -3 -m pip install PyQt5      （树莓派：sudo apt install python3-pyqt5）
"""

import configparser
import json
import re
import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QFormLayout, QPushButton, QLabel, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QSlider, QTableWidget, QTableWidgetItem,
    QMessageBox, QTabWidget, QTextEdit, QFileDialog,
    QHeaderView, QAbstractItemView,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor_gui import RecvThread  # 复用已跑通的 9001 接收线程

# --------------------------------------------------------------------------
# 词表与常量（与 视觉/src/sorting_vision 保持同源）
# --------------------------------------------------------------------------
COLOR_VOCAB = (
    "red", "orange", "yellow", "green", "cyan", "blue",
    "purple", "pink", "black", "white", "gray",
)
SHAPE_VOCAB = (
    "cube", "cuboid", "cylinder", "hexagonal_prism",
    "pentagonal_prism", "square_pyramid", "triangular_prism",
)
COLOR_CN = {
    "red": "红", "orange": "橙", "yellow": "黄", "green": "绿", "cyan": "青",
    "blue": "蓝", "purple": "紫", "pink": "粉", "black": "黑", "white": "白",
    "gray": "灰",
}
SHAPE_CN = {
    "cube": "正方体", "cuboid": "长方体", "cylinder": "圆柱",
    "hexagonal_prism": "六棱柱", "pentagonal_prism": "五棱柱",
    "square_pyramid": "四棱锥", "triangular_prism": "三棱柱",
}
BOX_IDS = (1, 2, 3, 4, 5, 6)
COORD_LIMIT_MM = 145.0          # ITEM_TASK 协议域 ±145.0mm
COORD_LIMIT_0_1MM = 1450
STALL_WARN_SEC = 3.0            # 超过这么久没有新帧 → 推理停滞告警

BOXMAP_SECTION = "BoxMap"
DROPPOINTS_SECTION = "DropPoints"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_ini() -> Path:
    """默认配置文件。

    权威判定（2026-09-15 复核）：以 `电控/deploy/sorting_config.ini` 为准 ——
    它逐项命中已冻结参数（steps_per_mm=80、travel_per_leg_mm=165、
    reach_limit_mm=82.5、workspace_limit=145、limit_switch_check=false、
    last_calibration_date=2026-09-15），并且唯一的主链路运行器
    `电控/deploy/run_chain.py`（含 9002 全链路监控）也在这个目录下。
    `电控/deployment/sorting_config.ini` 是更早、更薄的一代，只作后备。
    """
    repo = repo_root()
    primary = repo / "电控" / "deploy" / "sorting_config.ini"
    if primary.exists():
        return primary
    legacy = repo / "电控" / "deployment" / "sorting_config.ini"
    if legacy.exists():
        return legacy
    return Path("/home/pi/sorting_config.ini")


# --------------------------------------------------------------------------
# 纯逻辑：解析 / 序列化 / 校验（可离线自检，不依赖 Qt）
# --------------------------------------------------------------------------
def upsert_section(text: str, name: str, body: list[str]) -> str:
    """在 INI 文本里替换或追加一节，**逐字节保留其余内容（含注释）**。"""
    block = [f"[{name}]"] + list(body) + [""]
    lines = text.splitlines(keepends=True)
    header = re.compile(r"^\s*\[" + re.escape(name) + r"\]\s*$")

    start = None
    for i, line in enumerate(lines):
        if header.match(line.rstrip("\r\n")):
            start = i
            break

    if start is None:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] = lines[-1] + "\n"
        return "".join(lines) + "\n".join(block)

    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = j
            break

    return "".join(lines[:start]) + "\n".join(block) + "".join(lines[end:])


def format_box_map(mapping: dict[tuple[int, int], int]) -> list[str]:
    """(color_id, shape_id) -> box_id  →  INI 行，带注释。"""
    out = ["# (color_id, shape_id) = box_id   —— 对应表，现场冻结",
           "# color_id: " + ", ".join(f"{i}={c}" for i, c in enumerate(COLOR_VOCAB)),
           "# shape_id: " + ", ".join(f"{i}={s}" for i, s in enumerate(SHAPE_VOCAB)),
           "# 未列出的 (颜色,形状) 组合 = 未分配；运行时必须拒绝入格，不得猜。"]
    for (c, s), b in sorted(mapping.items()):
        out.append(f"{c},{s} = {b}")
    if not mapping:
        out.append("# （空 —— 现场标定后由总控面板写入）")
    return out


def parse_box_map(cfg: configparser.ConfigParser) -> dict[tuple[int, int], int]:
    result: dict[tuple[int, int], int] = {}
    if not cfg.has_section(BOXMAP_SECTION):
        return result
    for key, value in cfg.items(BOXMAP_SECTION):
        parts = key.split(",")
        if len(parts) != 2:
            continue
        try:
            c, s, b = int(parts[0]), int(parts[1]), int(value)
        except ValueError:
            continue
        result[(c, s)] = b
    return result


def format_drop_points(points: dict[int, tuple[float, float]]) -> list[str]:
    """box_id -> (x_mm, y_mm)  →  INI 行。"""
    out = ["# box_id = x_mm,y_mm   —— 六个货格的落点（原点=装置中心，域 ±145.0）",
           "# 实测填入；未填的货格禁止使用。"]
    for b in BOX_IDS:
        if b in points:
            x, y = points[b]
            out.append(f"{b} = {x:.2f},{y:.2f}")
    if not points:
        out.append("# （空 —— 现场标定后由总控面板写入）")
    return out


def parse_drop_points(cfg: configparser.ConfigParser) -> dict[int, tuple[float, float]]:
    result: dict[int, tuple[float, float]] = {}
    if not cfg.has_section(DROPPOINTS_SECTION):
        return result
    for key, value in cfg.items(DROPPOINTS_SECTION):
        try:
            b = int(key)
            x_str, y_str = value.split(",")
            result[b] = (float(x_str), float(y_str))
        except (ValueError, AttributeError):
            continue
    return result


COLOR_SECTION = "ColorThresholds"
DISPLAY_SECTION = "Display"
DISPLAY_NAMES_SECTION = "DisplayNames"

# 屏幕分辨率（树莓派那块屏）
DISPLAY_DEFAULT_W, DISPLAY_DEFAULT_H = 1024, 600
# 树莓派上中文字体的标准位置（fonts-wqy-zenhei）
PI_CJK_FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"


def default_display_names() -> dict[int, str]:
    """class_id -> 屏幕显示的货物名称，默认取形状中文名。

    赛题原文的信息示例是「五棱柱 / 正四面体」这类**形状名**，
    所以默认就叫形状名。用户可以逐条改成更具体的（如「红五棱柱」）。
    """
    return {i: SHAPE_CN[name] for i, name in enumerate(SHAPE_VOCAB)}


def font_renders_cjk(font_path: str) -> bool:
    """判断字体能否真正渲染中文（而不是画成同一个方块）。

    做法：渲染两个**不同的**汉字，比较位图。字体缺字形时两个都会落成同一个
    .notdef 方块 → 位图相同 → 判为不支持。
    """
    try:
        from PIL import Image, ImageDraw, ImageFont  # 懒加载
    except ImportError:
        return False
    try:
        font = ImageFont.truetype(font_path, 48)
    except Exception:
        return False

    def glyph(ch: str) -> bytes:
        img = Image.new("L", (96, 96), 0)
        ImageDraw.Draw(img).text((0, 0), ch, font=font, fill=255)
        return img.tobytes()

    return glyph("五") != glyph("棱")


def find_default_cjk_font() -> str:
    """挑一个本机可用的中文字体（Windows 开发机 / 树莓派各自动适配）。"""
    candidates = []
    if sys.platform.startswith("win"):
        candidates = [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
                      r"C:\Windows\Fonts\simsun.ttc"]
    candidates.append(PI_CJK_FONT)
    for path in candidates:
        if Path(path).exists() and font_renders_cjk(path):
            return path
    return ""


def parse_display_names(cfg: configparser.ConfigParser) -> dict[int, str]:
    """从 [DisplayNames] 读 class_id -> 显示名称；缺省用形状中文名。"""
    names = default_display_names()
    if not cfg.has_section(DISPLAY_NAMES_SECTION):
        return names
    for key, value in cfg.items(DISPLAY_NAMES_SECTION):
        try:
            idx = int(key)
        except ValueError:
            continue
        if 0 <= idx < len(SHAPE_VOCAB) and value.strip():
            names[idx] = value.strip()
    return names


def format_display_names(names: dict[int, str]) -> list[str]:
    out = [
        "# 屏幕显示的货物名称（class_id = 形状ID → 中文名）",
        "# 赛题要求显示「具体的货物名称」；官方信息示例是形状名（五棱柱 / 正四面体）。",
        "# ⚠️ 该表只按【形状】取名 —— 同一个形状不同颜色会显示同一个名字。",
        "#    若担心裁判判「信息错误」，可改成带颜色的名字（如「红五棱柱」）。",
    ]
    for i, shape in enumerate(SHAPE_VOCAB):
        out.append(f"{i} = {names.get(i, SHAPE_CN[shape])}")
    return out


def parse_motion_constants(text: str) -> dict[str, int]:
    """从 ec_motion_plan.h 抓关键常量，用于和规范抓取时序对照。"""
    keys = ("EC_MOTION_PICK_X_MM10", "EC_MOTION_PICK_Y_MM10",
            "EC_MOTION_HOME_X_MM10", "EC_MOTION_HOME_Y_MM10",
            "EC_MOTION_WORKSPACE_LIMIT_MM10",
            # 2026-09-18：单一 EC_MOTION_REACH_LIMIT_MM10 已拆成 X/Y 两个
            # （实测可用行程 X=210mm / Y=190mm，一个宏塞不下两个值）
            "EC_MOTION_REACH_LIMIT_X_MM10", "EC_MOTION_REACH_LIMIT_Y_MM10")
    out: dict[str, int] = {}
    for key in keys:
        m = re.search(r"#define\s+" + re.escape(key) + r"\s+\(?\s*(-?\d+)\s*\)?", text)
        if m:
            out[key] = int(m.group(1))
    return out


def check_pick_sequence(consts: dict[str, int]) -> list[str]:
    """对照规范时序（docs/design/抓取时序-2026-09-15.md）找出与赛题冲突之处。"""
    warns: list[str] = []
    px = consts.get("EC_MOTION_PICK_X_MM10")
    py = consts.get("EC_MOTION_PICK_Y_MM10")
    if px == 0 and py == 0:
        warns.append(
            "🔴 抓取点被写死成装置中心 (0,0)。赛题要求【货物位置随机、不可触碰】，"
            "抓取点必须每件不同。照现状跑＝跑到中心空夹一次 → 抓空却计成功数 → 数量全错。"
            "详见 docs/design/抓取时序-2026-09-15.md")
    elif px is None or py is None:
        warns.append("🟡 抓取点常量已不在头文件里（可能已改成参数）—— "
                     "请确认 ec_app.c 也同步把抓取点传进来了")
    rx = consts.get("EC_MOTION_REACH_LIMIT_X_MM10")
    ry = consts.get("EC_MOTION_REACH_LIMIT_Y_MM10")
    if rx is not None and ry is not None:
        warns.append(
            f"ℹ️ 机械可达域 X ±{rx/10:.1f}mm / Y ±{ry/10:.1f}mm 已生效"
            f"（比协议域 ±145.0mm 更紧，交付坐标以它为准）")
    elif consts.get("EC_MOTION_REACH_LIMIT_MM10") is not None:
        warns.append("🟡 头文件里还是旧的单一 EC_MOTION_REACH_LIMIT_MM10"
                     "（2026-09-18 应已拆成 X/Y 两个宏），请确认没回退")
    return warns


# 规范抓取时序（9 步）。「坐标来源」标明每步用的是固定值还是变动的值。
# 2026-09-15 修正：**删掉了"回原点 (0,0)"那一步** —— 相机固定在装置中心，
# 夹爪停到 (0,0) 会正好挡住镜头（用户确认"会挡着，这个是肯定的"）。
# 停放位只回 HOME（角落），它同时是"让开视野"和"循环闭合"的那一步。
CANONICAL_FLOW = (
    ("①", "XY → HOME (角落 -80.0, -80.0)", "HOME 常量", "固定"),
    ("②", "【视觉确认】请求并等一张新图 → 得到本件的物品坐标 (x_i,y_i) + box_id",
     "视觉（每件不同）", "**变动**"),
    ("③", "XY → (x_i, y_i)", "物品坐标（视觉给的）", "**变动**"),
    ("④", "Z 下降（张开）", "舵机脉宽", "固定"),
    ("⑤", "Z 上升（闭合＝夹住）", "舵机脉宽", "固定"),
    ("⑥", "XY → (x_b, y_b)", "落料点（六盒表查出来的）", "固定"),
    ("⑦", "Z 下降（张开＝放料）", "舵机脉宽", "固定"),
    ("⑧", "Z 上升（闭合＝复位）", "舵机脉宽", "固定"),
    ("⑨", "XY → HOME（回停放位，为下一件让开视野）↺ 回到 ①", "HOME 常量", "固定"),
)


# 颜色判定阈值（HSL）。默认值 = 视觉/src/sorting_vision/color_quant.py:354-385 的硬编码值。
# ⚠️ 一个数都不许乱改 —— 改了就和线上算法对不上了。
COLOR_THRESHOLD_KEYS = (
    ("s_achromatic", 0.12),   # 饱和度低于它 → 黑/白/灰
    ("l_black", 0.15),        # 明度低于它 → 黑
    ("l_white", 0.85),        # 明度高于它 → 白
    ("hue_red_end", 15.0),
    ("hue_orange_end", 45.0),
    ("hue_yellow_end", 70.0),
    ("hue_green_end", 165.0),
    ("hue_cyan_end", 200.0),
    ("hue_blue_end", 255.0),
    ("hue_purple_end", 285.0),
    ("hue_red_start", 345.0),  # 色相 ≥ 它也算红（红色跨 0 度）
)


def classify_rgb(rgb: tuple[int, int, int],
                 th: dict[str, float]) -> tuple[str, tuple[float, float, float]]:
    """按给定阈值把 RGB 判成颜色名，返回 (颜色名, (h, s, l))。

    算法与 `视觉/src/sorting_vision/color_quant.py` 的 `rgb_to_hsl` + `color_name`
    **逐行等价**（含 s<0.12 走黑白灰、红色跨 0 度）。改这里必须同步改那边。
    """
    r, g, b = (c / 255.0 for c in rgb)
    hi, lo = max(r, g, b), min(r, g, b)
    level = (hi + lo) / 2
    if hi == lo:
        hue01 = sat = 0.0
    else:
        delta = hi - lo
        sat = delta / (2 - hi - lo) if level > 0.5 else delta / (hi + lo)
        if hi == r:
            hue01 = (g - b) / delta + (6 if g < b else 0)
        elif hi == g:
            hue01 = (b - r) / delta + 2
        else:
            hue01 = (r - g) / delta + 4
        hue01 /= 6

    hsl = (hue01, sat, level)
    if sat < th["s_achromatic"]:
        if level < th["l_black"]:
            return "black", hsl
        if level > th["l_white"]:
            return "white", hsl
        return "gray", hsl

    hue = hue01 * 360
    if hue < th["hue_red_end"] or hue >= th["hue_red_start"]:
        return "red", hsl
    if hue < th["hue_orange_end"]:
        return "orange", hsl
    if hue < th["hue_yellow_end"]:
        return "yellow", hsl
    if hue < th["hue_green_end"]:
        return "green", hsl
    if hue < th["hue_cyan_end"]:
        return "cyan", hsl
    if hue < th["hue_blue_end"]:
        return "blue", hsl
    if hue < th["hue_purple_end"]:
        return "purple", hsl
    return "pink", hsl


def parse_color_thresholds(cfg: configparser.ConfigParser) -> dict[str, float]:
    th = {key: default for key, default in COLOR_THRESHOLD_KEYS}
    if not cfg.has_section(COLOR_SECTION):
        return th
    for key, _ in COLOR_THRESHOLD_KEYS:
        try:
            th[key] = float(cfg.get(COLOR_SECTION, key))
        except (ValueError, configparser.Error):
            pass
    return th


def format_color_thresholds(th: dict[str, float]) -> list[str]:
    out = [
        "# 颜色判定阈值（HSL）—— 现场补光/白平衡变了就重新标定这一节",
        "# ⚠️ 目前 color_quant.py 里是硬编码的；要让这里的值真正生效，",
        "#    需把 color_name() 改成读本节（已列入协作任务 02）。",
        "# 面板「5 颜色标定」区可实时试算：输入 RGB 看判成什么颜色。",
    ]
    for key, default in COLOR_THRESHOLD_KEYS:
        out.append(f"{key} = {th.get(key, default)}")
    return out


SKIP_PARAM_SECTIONS = (BOXMAP_SECTION, DROPPOINTS_SECTION)


def parse_scalar_params(text: str) -> list[tuple[str, str, str]]:
    """列出全部 (节, 键, 值)，跳过由本面板专门管理的两节。

    保留键的原始大小写（configparser 默认会转小写，那样写回就改了文件）。
    """
    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    cfg.read_string(text)
    out: list[tuple[str, str, str]] = []
    for sec in cfg.sections():
        if sec in SKIP_PARAM_SECTIONS:
            continue
        for key, value in cfg.items(sec):
            out.append((sec, key, value))
    return out


def set_ini_value(text: str, section: str, key: str, value: str) -> str:
    """只替换某节里的某一行 `key = ...`，**其余内容（含行内注释）逐字节保留**。

    找不到该节或该键时原样返回（新建节由 upsert_section 负责）。
    """
    lines = text.splitlines(keepends=True)
    header = re.compile(r"^\s*\[" + re.escape(section) + r"\]\s*$")
    start = None
    for i, line in enumerate(lines):
        if header.match(line.rstrip("\r\n")):
            start = i
            break
    if start is None:
        return text

    key_re = re.compile(r"^(\s*" + re.escape(key) + r"\s*[=:]\s*)(.*)$")
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            break
        raw = lines[j].rstrip("\r\n")
        eol = lines[j][len(raw):] or "\n"
        m = key_re.match(raw)
        if not m:
            continue
        body = m.group(2)
        comment = ""
        if "#" in body:
            comment = "  " + body[body.index("#"):].rstrip()
        lines[j] = f"{m.group(1)}{value}{comment}{eol}"
        return "".join(lines)
    return text


def open_socket(host: str, port: int, timeout: float = 5.0):
    """建立 TCP 连接并恢复阻塞模式。两条监控通道共用。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, port))
    s.settimeout(None)
    return s


def validate(box_map: dict[tuple[int, int], int],
             drop_points: dict[int, tuple[float, float]]) -> tuple[list[str], list[str]]:
    """返回 (errors, warnings)。errors 非空时禁止烧录。"""
    errors: list[str] = []
    warnings: list[str] = []

    if not box_map and not drop_points:
        errors.append("对应表和落点表都是空的 —— 没有任何东西可烧录。")

    used_boxes: set[int] = set()
    for (c, s), b in sorted(box_map.items()):
        if not 1 <= b <= 6:
            errors.append(f"货格号越界: ({c},{s}) -> {b}（必须 1..6）")
        if not 0 <= c < len(COLOR_VOCAB):
            errors.append(f"颜色号越界: ({c},{s}) 中 c={c}（必须 0..{len(COLOR_VOCAB) - 1}）")
        if not 0 <= s < len(SHAPE_VOCAB):
            errors.append(f"形状号越界: ({c},{s}) 中 s={s}（必须 0..{len(SHAPE_VOCAB) - 1}）")
        used_boxes.add(b)

    if box_map:
        unused = [b for b in BOX_IDS if b not in used_boxes]
        if unused:
            warnings.append(f"这些货格没有被任何 (颜色,形状) 组合使用: {unused}")

    for b, (x, y) in sorted(drop_points.items()):
        if b not in BOX_IDS:
            errors.append(f"落点表的货格号越界: {b}（必须 1..6）")
        if abs(x) > COORD_LIMIT_MM or abs(y) > COORD_LIMIT_MM:
            errors.append(f"货格 {b} 的落点超出协议域 ±{COORD_LIMIT_MM}mm: ({x}, {y})")
        if x == 0.0 and y == 0.0:
            errors.append(f"货格 {b} 的落点是 (0, 0) —— 装置中心不可能是落料点，"
                          "多半是没填。")

    missing = sorted(used_boxes - set(drop_points))
    if missing:
        errors.append(f"对应表用到了货格 {missing}，但落点表里没有它们的坐标。")

    if not box_map:
        warnings.append("对应表为空：运行时会拒识所有货物（这是安全的失败方向）。")

    return errors, warnings


# --------------------------------------------------------------------------
# 自检
# --------------------------------------------------------------------------
def _selftest() -> int:
    sample = (
        "# 这是注释，必须保留\n"
        "[Vision]\n"
        "conf_threshold = 0.5\n"
        "\n"
        "[Debug]\n"
        "# 尾注释也保留\n"
        "verbose_logging = false\n"
    )

    # 1. 追加新节：原有内容一字不动
    once = upsert_section(sample, BOXMAP_SECTION, ["0,0 = 1"])
    assert "# 这是注释，必须保留" in once, "注释被吞了"
    assert "conf_threshold = 0.5" in once
    assert "[BoxMap]" in once and "0,0 = 1" in once
    assert once.count("[BoxMap]") == 1

    # 2. 重复写入是替换而不是重复追加
    twice = upsert_section(once, BOXMAP_SECTION, ["0,0 = 2"])
    assert twice.count("[BoxMap]") == 1, "节被重复追加"
    assert "0,0 = 1" not in twice and "0,0 = 2" in twice
    assert "[Debug]" in twice and "verbose_logging = false" in twice, "后面的节被吃掉"

    # 3. 插在中间不破坏后继节
    mid = upsert_section(sample, "Vision", ["conf_threshold = 0.9"])
    assert mid.count("[Vision]") == 1
    assert "conf_threshold = 0.9" in mid and "conf_threshold = 0.5" not in mid
    assert "[Debug]" in mid and "verbose_logging = false" in mid

    # 4. 往返：格式化成 INI 再解析回来要一致
    #    六格全覆盖，才能作为「干净数据」的基准（少用货格本来就该报警告）
    box_map = {(0, 0): 1, (5, 6): 6, (3, 2): 3, (1, 1): 2, (2, 3): 4, (4, 5): 5}
    points = {
        1: (12.5, -88.0), 2: (0.0, 95.25), 3: (-40.0, 40.0),
        4: (140.0, 140.0), 5: (-140.0, -140.0), 6: (-12.5, 88.0),
    }
    text = upsert_section(
        upsert_section(sample, BOXMAP_SECTION, format_box_map(box_map)),
        DROPPOINTS_SECTION, format_drop_points(points),
    )
    cfg = configparser.ConfigParser()
    cfg.read_string(text)
    assert parse_box_map(cfg) == box_map, f"对应表往返失败: {parse_box_map(cfg)}"
    assert parse_drop_points(cfg) == points, f"落点表往返失败: {parse_drop_points(cfg)}"

    # 5. 校验：干净数据无错
    errs, warns = validate(box_map, points)
    assert errs == [], f"干净数据不该报错: {errs}"
    assert warns == [], f"干净数据不该报警: {warns}"

    # 5b. 少用货格 → 警告（不是错误）
    errs, warns = validate({(0, 0): 1, (5, 6): 6, (3, 2): 3}, points)
    assert errs == [], errs
    assert any("没有被任何" in w for w in warns), warns

    # 6. 校验：抓到真问题
    errs, _ = validate({(0, 0): 9}, {1: (0.0, 0.0)})
    assert any("货格号越界" in e for e in errs), errs
    errs, _ = validate({(0, 0): 1}, {1: (0.0, 0.0)})
    assert any("装置中心" in e for e in errs), errs
    errs, _ = validate({(99, 0): 1}, {1: (1.0, 1.0)})
    assert any("颜色号越界" in e for e in errs), errs
    errs, _ = validate({(0, 0): 4}, {1: (1.0, 1.0)})
    assert any("货格 [4]" in e for e in errs), errs
    errs, _ = validate({(0, 0): 1}, {1: (999.0, 0.0)})
    assert any("协议域" in e for e in errs), errs
    errs, _ = validate({}, {})
    assert any("都是空的" in e for e in errs), errs

    # 7. 校验：空对应表 → 警告而非错误
    errs, warns = validate({}, {1: (1.0, 1.0)})
    assert errs == [], errs
    assert any("对应表为空" in w for w in warns), warns

    # 8. 单键写入：只动那一行，其余逐字节保留
    fixed = set_ini_value(sample, "Vision", "conf_threshold", "0.7")
    assert "conf_threshold = 0.7" in fixed
    assert "# 这是注释，必须保留" in fixed and "[Debug]" in fixed
    assert set_ini_value(sample, "Vision", "nope", "1") == sample, "不存在的键不该改文件"
    assert set_ini_value(sample, "NoSuch", "x", "1") == sample, "不存在的节不该改文件"
    got = set_ini_value("[A]\nk = 1  # 说明\n[B]\nx = 2\n", "A", "k", "9")
    assert "k = 9  # 说明" in got, got
    assert "x = 2" in got, got

    # 9. 参数枚举：跳过自管两节、保留键的大小写
    params = parse_scalar_params(text)
    secs = {p[0] for p in params}
    assert "BoxMap" not in secs and "DropPoints" not in secs, secs
    assert "Vision" in secs and "Debug" in secs, secs
    assert ("Vision", "conf_threshold", "0.5") in params, params

    # 10. 颜色判定必须与 color_quant.py 逐行等价（(205,25,25)/(25,175,60) 取自它的自测）
    th = {k: v for k, v in COLOR_THRESHOLD_KEYS}
    assert classify_rgb((205, 25, 25), th)[0] == "red", classify_rgb((205, 25, 25), th)
    assert classify_rgb((25, 175, 60), th)[0] == "green", classify_rgb((25, 175, 60), th)
    assert classify_rgb((0, 0, 0), th)[0] == "black"
    assert classify_rgb((255, 255, 255), th)[0] == "white"
    assert classify_rgb((128, 128, 128), th)[0] == "gray"
    assert classify_rgb((0, 0, 255), th)[0] == "blue"
    assert classify_rgb((255, 255, 0), th)[0] == "yellow"
    assert classify_rgb((0, 255, 255), th)[0] == "cyan"
    assert classify_rgb((128, 0, 255), th)[0] == "purple"
    assert classify_rgb((255, 0, 255), th)[0] == "pink"
    assert classify_rgb((255, 128, 0), th)[0] == "orange"
    # 色相换算不能错位
    assert abs(classify_rgb((255, 0, 0), th)[1][0] * 360) < 1e-9
    assert abs(classify_rgb((0, 0, 255), th)[1][0] * 360 - 240) < 1e-9
    # 阈值真的可调：把 s_achromatic 拉到 0.9，(205,25,25) 该掉进灰
    th2 = dict(th)
    th2["s_achromatic"] = 0.9
    assert classify_rgb((205, 25, 25), th2)[0] == "gray", classify_rgb((205, 25, 25), th2)

    # 11. 阈值节往返 + 缺节回默认
    text2 = upsert_section(text, COLOR_SECTION, format_color_thresholds(th))
    cfg2 = configparser.ConfigParser()
    cfg2.read_string(text2)
    assert parse_color_thresholds(cfg2) == th, parse_color_thresholds(cfg2)
    assert parse_color_thresholds(configparser.ConfigParser()) == th, "缺节时要回默认值"

    # 12. 屏幕名称表：默认取形状中文名，且必须覆盖全部 7 个形状类
    dn = default_display_names()
    assert len(dn) == len(SHAPE_VOCAB) == 7, dn
    assert dn[4] == "五棱柱", dn          # 赛题示例里的那个
    assert dn[5] == "四棱锥", dn
    assert parse_display_names(configparser.ConfigParser()) == dn, "缺节要回默认"
    text3 = upsert_section(text, DISPLAY_NAMES_SECTION, format_display_names(dn))
    cfg3 = configparser.ConfigParser()
    cfg3.read_string(text3)
    assert parse_display_names(cfg3) == dn

    # 13. 中文字体检测：能识别出「不含中文的字体」
    assert font_renders_cjk(r"C:\Windows\Fonts\simhei.ttf") is True, "simhei 应含中文"
    assert font_renders_cjk(r"C:\Windows\Fonts\consola.ttf") is False, "consola 不含中文，应判 False"
    assert font_renders_cjk(r"C:\不存在的字体.ttf") is False, "不存在的文件应判 False"

    # 14. 抓取时序对照：必须能认出「抓取点被写死」这个 bug
    hdr = ("#define EC_MOTION_PICK_X_MM10 0\n#define EC_MOTION_PICK_Y_MM10 0\n"
           "#define EC_MOTION_HOME_X_MM10 (-800)\n#define EC_MOTION_HOME_Y_MM10 (-800)\n"
           "#define EC_MOTION_WORKSPACE_LIMIT_MM10 1450\n"
           "#define EC_MOTION_REACH_LIMIT_X_MM10 1050\n"
           "#define EC_MOTION_REACH_LIMIT_Y_MM10 950\n")
    c = parse_motion_constants(hdr)
    assert c["EC_MOTION_HOME_X_MM10"] == -800, c
    assert c["EC_MOTION_REACH_LIMIT_X_MM10"] == 1050, c
    assert c["EC_MOTION_REACH_LIMIT_Y_MM10"] == 950, c
    w1 = check_pick_sequence(c)
    assert any("抓取点被写死" in w for w in w1), w1
    # 抓取点常量被删掉（即已改成参数）→ 换一条提示
    w2 = check_pick_sequence({"EC_MOTION_HOME_X_MM10": -800})
    assert any("已不在头文件里" in w for w in w2), w2
    # 规范时序必须是 9 步（已删掉"回原点(0,0)"那步），且含两步"变动"
    assert len(CANONICAL_FLOW) == 9, CANONICAL_FLOW
    assert sum(1 for s in CANONICAL_FLOW if "变动" in s[3]) == 2, CANONICAL_FLOW
    assert not any("回原点" in s[1] for s in CANONICAL_FLOW), "不该再有回 (0,0) 这一步"

    print("SELFTEST OK  (14 组断言全部通过)")
    return 0


# --------------------------------------------------------------------------
# Qt 部件（仅 GUI 模式使用）
# --------------------------------------------------------------------------
if "--selftest" not in sys.argv:

    class ControlPanel(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("智能分拣装置 · 总控面板")
            self.resize(1150, 780)

            self.sock = None
            self.recv_thread = None
            self.connected = False
            self.sock2 = None
            self.recv_thread2 = None
            self.connected2 = False
            self.box_map: dict[tuple[int, int], int] = {}
            self.drop_points: dict[int, tuple[float, float]] = {}
            self.ini_path = default_ini()
            self.last_frame_at: datetime | None = None

            self.stall_timer = QTimer()
            self.stall_timer.timeout.connect(self._check_stall)

            self._build_ui()
            self._load_ini()

        # ---------------- 布局 ----------------
        def _build_ui(self) -> None:
            central = QWidget()
            self.setCentralWidget(central)
            root = QVBoxLayout(central)

            root.addWidget(self._build_conn_bar())

            tabs = QTabWidget()
            tabs.addTab(self._build_tab_monitor(), "1 实时监控")
            tabs.addTab(self._build_tab_params(), "2 参数")
            tabs.addTab(self._build_tab_table(), "3 对应表")
            tabs.addTab(self._build_tab_color(), "5 颜色标定")
            tabs.addTab(self._build_tab_display(), "6 屏幕显示")
            tabs.addTab(self._build_tab_flow(), "7 抓取时序")
            tabs.addTab(self._build_tab_flash(), "4 烧录")
            root.addWidget(tabs)

        def _build_conn_bar(self) -> QGroupBox:
            box = QGroupBox("连接（MaixCAM 监控端口）")
            lay = QHBoxLayout()
            lay.addWidget(QLabel("IP:"))
            self.ip_input = QLineEdit("172.20.10.2")
            self.ip_input.setMaximumWidth(130)
            lay.addWidget(self.ip_input)
            lay.addWidget(QLabel("端口:"))
            self.port_input = QLineEdit("9001")
            self.port_input.setMaximumWidth(70)
            lay.addWidget(self.port_input)

            self.connect_btn = QPushButton("连接")
            self.connect_btn.clicked.connect(self.toggle_connection)
            lay.addWidget(self.connect_btn)

            self.status_label = QLabel("未连接")
            self.status_label.setStyleSheet("color:#c00;font-weight:bold;")
            lay.addWidget(self.status_label)
            lay.addStretch()
            lay.addWidget(QLabel("本机模式：把 IP 填 127.0.0.1 即可"))
            box.setLayout(lay)
            return box

        def _build_tab_monitor(self) -> QWidget:
            w = QWidget()
            lay = QVBoxLayout(w)
            sub = QTabWidget()
            sub.addTab(self._build_page_maix(), "MaixCAM 原始检测 (9001)")
            sub.addTab(self._build_page_pi(), "全链路 视觉→电控→结果 (9002)")
            lay.addWidget(sub)
            return w

        def _build_page_maix(self) -> QWidget:
            w = QWidget()
            lay = QVBoxLayout(w)

            stats = QGroupBox("状态")
            g = QGridLayout()
            self.fps_label = QLabel("--")
            self.det_label = QLabel("--")
            self.frame_at_label = QLabel("--")
            self.stall_label = QLabel("等待数据")
            self.stall_label.setStyleSheet("font-weight:bold;")
            g.addWidget(QLabel("FPS:"), 0, 0)
            g.addWidget(self.fps_label, 0, 1)
            g.addWidget(QLabel("检测数量:"), 1, 0)
            g.addWidget(self.det_label, 1, 1)
            g.addWidget(QLabel("最后收到帧:"), 0, 2)
            g.addWidget(self.frame_at_label, 0, 3)
            g.addWidget(QLabel("推理停滞告警:"), 1, 2)
            g.addWidget(self.stall_label, 1, 3)
            g.setColumnStretch(4, 1)
            stats.setLayout(g)
            lay.addWidget(stats)

            note = QLabel(
                "“树莓派还在发指令、摄像头已经停了”这类故障，心跳是看不出来的 —— "
                "只有“最后收到帧”的时间在涨才说明视觉真的活着。"
            )
            note.setWordWrap(True)
            note.setStyleSheet("color:#555;")
            lay.addWidget(note)

            self.shot_btn = QPushButton("保存当前帧到 MaixCAM (/root/screenshots/)")
            self.shot_btn.clicked.connect(self.save_screenshot)
            self.shot_btn.setEnabled(False)
            lay.addWidget(self.shot_btn)

            lay.addWidget(QLabel("检测结果（3001 原始输出）:"))
            self.det_table = QTableWidget()
            self.det_table.setColumnCount(5)
            self.det_table.setHorizontalHeaderLabels(
                ["类别ID", "类别名", "置信度", "中心X", "中心Y"])
            self.det_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            lay.addWidget(self.det_table)
            return w

        def _build_page_pi(self) -> QWidget:
            """全链路页：视觉→树莓派→STM32 指令→执行结果（树莓派 9002 广播）。"""
            w = QWidget()
            lay = QVBoxLayout(w)

            bar = QGroupBox("连接（树莓派链路监控端口）")
            bl = QHBoxLayout()
            bl.addWidget(QLabel("树莓派 IP:"))
            self.ip2_input = QLineEdit("172.20.10.8")
            self.ip2_input.setMaximumWidth(130)
            bl.addWidget(self.ip2_input)
            bl.addWidget(QLabel("端口:"))
            self.port2_input = QLineEdit("9002")
            self.port2_input.setMaximumWidth(70)
            bl.addWidget(self.port2_input)
            self.connect2_btn = QPushButton("连接")
            self.connect2_btn.clicked.connect(self.toggle_pi)
            bl.addWidget(self.connect2_btn)
            self.status2_label = QLabel("未连接")
            self.status2_label.setStyleSheet("color:#c00;font-weight:bold;")
            bl.addWidget(self.status2_label)
            bl.addStretch()
            bar.setLayout(bl)
            lay.addWidget(bar)

            stages = QGroupBox("链路三阶段")
            g = QGridLayout()
            g.addWidget(QLabel("① 视觉 → 树莓派"), 0, 0)
            self.v_stage = QLabel("等待数据")
            g.addWidget(self.v_stage, 0, 1)
            g.addWidget(QLabel("② 树莓派 → STM32"), 0, 2)
            self.c_stage = QLabel("等待数据")
            g.addWidget(self.c_stage, 0, 3)
            g.addWidget(QLabel("③ STM32 → 树莓派"), 0, 4)
            self.r_stage = QLabel("等待数据")
            g.addWidget(self.r_stage, 0, 5)

            g.addWidget(QLabel("批次 task_id:"), 1, 0)
            self.v_task = QLabel("--")
            g.addWidget(self.v_task, 1, 1)
            g.addWidget(QLabel("轮次/任务:"), 1, 2)
            self.c_ids = QLabel("--")
            g.addWidget(self.c_ids, 1, 3)
            g.addWidget(QLabel("结果:"), 1, 4)
            self.r_result = QLabel("--")
            g.addWidget(self.r_result, 1, 5)

            g.addWidget(QLabel("目标数:"), 2, 0)
            self.v_count = QLabel("--")
            g.addWidget(self.v_count, 2, 1)
            g.addWidget(QLabel("目标序号/类别:"), 2, 2)
            self.c_target = QLabel("--")
            g.addWidget(self.c_target, 2, 3)
            g.addWidget(QLabel("结果码/依据:"), 2, 4)
            self.r_code = QLabel("--")
            g.addWidget(self.r_code, 2, 5)

            g.addWidget(QLabel("X (0.1mm):"), 3, 0)
            self.c_x = QLabel("--")
            g.addWidget(self.c_x, 3, 1)
            g.addWidget(QLabel("Y (0.1mm):"), 3, 2)
            self.c_y = QLabel("--")
            g.addWidget(self.c_y, 3, 3)
            g.addWidget(QLabel("最后更新:"), 3, 4)
            self.last2_label = QLabel("--")
            g.addWidget(self.last2_label, 3, 5)
            g.setColumnStretch(6, 1)
            stages.setLayout(g)
            lay.addWidget(stages)

            tip = QLabel(
                "顺序对不上就是断点所在：① 有、② 没有 = 树莓派没发指令；"
                "② 有、③ 没有 = STM32 没回结果或回错了。"
            )
            tip.setWordWrap(True)
            tip.setStyleSheet("color:#555;")
            lay.addWidget(tip)

            lay.addWidget(QLabel("视觉批次目标（target_seq / 类别ID / 盒号）:"))
            self.pi_vision_table = QTableWidget()
            self.pi_vision_table.setColumnCount(3)
            self.pi_vision_table.setHorizontalHeaderLabels(["目标序号", "类别ID", "盒号"])
            self.pi_vision_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            lay.addWidget(self.pi_vision_table)

            lay.addWidget(QLabel("全链路事件流:"))
            self.pi_log = QTextEdit()
            self.pi_log.setReadOnly(True)
            lay.addWidget(self.pi_log)
            return w

        def _build_tab_params(self) -> QWidget:
            w = QWidget()
            lay = QVBoxLayout(w)

            live = QGroupBox("视觉参数（实时下发到 MaixCAM，立即生效）")
            form = QFormLayout()

            crow = QHBoxLayout()
            self.conf_slider = QSlider(Qt.Horizontal)
            self.conf_slider.setRange(10, 95)
            self.conf_slider.setValue(50)          # 冻结值 0.5
            self.conf_slider.valueChanged.connect(
                lambda v: self.conf_label.setText(f"{v / 100:.2f}"))
            self.conf_label = QLabel("0.50")
            crow.addWidget(self.conf_slider)
            crow.addWidget(self.conf_label)
            form.addRow("置信度阈值 conf_th:", crow)

            irow = QHBoxLayout()
            self.iou_slider = QSlider(Qt.Horizontal)
            self.iou_slider.setRange(10, 95)
            self.iou_slider.setValue(45)
            self.iou_slider.valueChanged.connect(
                lambda v: self.iou_label.setText(f"{v / 100:.2f}"))
            self.iou_label = QLabel("0.45")
            irow.addWidget(self.iou_slider)
            irow.addWidget(self.iou_label)
            form.addRow("IOU 阈值 iou_th:", irow)

            self.push_live_btn = QPushButton("立即下发到 MaixCAM")
            self.push_live_btn.clicked.connect(self.push_live_params)
            self.push_live_btn.setEnabled(False)
            form.addRow("", self.push_live_btn)
            live.setLayout(form)
            lay.addWidget(live)

            filebox = QGroupBox("配置文件参数（全部条目可改；点“4 烧录”的 ① 才写盘）")
            f2 = QVBoxLayout()
            self.param_table = QTableWidget()
            self.param_table.setColumnCount(3)
            self.param_table.setHorizontalHeaderLabels(["节", "键", "值"])
            phead = self.param_table.horizontalHeader()
            phead.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            phead.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            phead.setSectionResizeMode(2, QHeaderView.Stretch)
            f2.addWidget(self.param_table)
            hint = QLabel(
                "列的是配置文件里**实际存在的**条目 —— 换哪份配置就跟着变，不写死键名。"
                "左边滑块只用于实时下发，改它不会动文件。"
            )
            hint.setWordWrap(True)
            hint.setStyleSheet("color:#555;")
            f2.addWidget(hint)
            filebox.setLayout(f2)
            lay.addWidget(filebox)
            return w

        def _build_tab_table(self) -> QWidget:
            w = QWidget()
            lay = QVBoxLayout(w)

            add = QGroupBox("新增 / 修改一条对应关系")
            row = QHBoxLayout()
            row.addWidget(QLabel("颜色:"))
            self.color_combo = QComboBox()
            for i, c in enumerate(COLOR_VOCAB):
                self.color_combo.addItem(f"{COLOR_CN[c]} ({c})", i)
            row.addWidget(self.color_combo)

            row.addWidget(QLabel("形状:"))
            self.shape_combo = QComboBox()
            for i, s in enumerate(SHAPE_VOCAB):
                self.shape_combo.addItem(f"{SHAPE_CN[s]} ({s})", i)
            row.addWidget(self.shape_combo)

            row.addWidget(QLabel("→ 货格:"))
            self.box_combo = QComboBox()
            for b in BOX_IDS:
                self.box_combo.addItem(f"{b} 号", b)
            row.addWidget(self.box_combo)

            add_btn = QPushButton("写入")
            add_btn.clicked.connect(self.add_mapping)
            row.addWidget(add_btn)
            row.addStretch()
            add.setLayout(row)
            lay.addWidget(add)

            lay.addWidget(QLabel("对应表  (color_id, shape_id) → box_id"))
            self.map_table = QTableWidget()
            self.map_table.setColumnCount(4)
            self.map_table.setHorizontalHeaderLabels(["颜色", "形状", "货格", "操作"])
            self.map_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.map_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            lay.addWidget(self.map_table)

            lay.addWidget(QLabel("六个货格落点（mm，原点=装置中心，域 ±145.0）"))
            self.dp_table = QTableWidget()
            self.dp_table.setColumnCount(3)
            self.dp_table.setHorizontalHeaderLabels(["货格", "X (mm)", "Y (mm)"])
            self.dp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.dp_table.setRowCount(len(BOX_IDS))
            for r, b in enumerate(BOX_IDS):
                it = QTableWidgetItem(f"{b}")
                it.setFlags(Qt.ItemIsEnabled)
                self.dp_table.setItem(r, 0, it)
                for col in (1, 2):
                    spin = QDoubleSpinBox()
                    spin.setRange(-COORD_LIMIT_MM, COORD_LIMIT_MM)
                    spin.setDecimals(2)
                    spin.setSingleStep(0.5)
                    spin.setSpecialValueText("未填")
                    spin.setValue(0.0)
                    spin.valueChanged.connect(self._refresh_issues)
                    self.dp_table.setCellWidget(r, col, spin)
            lay.addWidget(self.dp_table)

            self.issues_label = QLabel("--")
            self.issues_label.setWordWrap(True)
            lay.addWidget(self.issues_label)
            return w

        def _build_tab_color(self) -> QWidget:
            """颜色标定：调 HSL 阈值 + 本地试算。不连设备、不改线上行为。"""
            w = QWidget()
            lay = QVBoxLayout(w)

            calc = QGroupBox("试算器（纯本地，不连设备）")
            g = QGridLayout()
            self.rgb_spins = []
            for col, name in enumerate(("R", "G", "B")):
                g.addWidget(QLabel(f"{name}:"), 0, col * 2)
                spin = QSpinBox()
                spin.setRange(0, 255)
                spin.setValue((205, 25, 25)[col])   # 先赋值再连信号，避免构造期回调
                spin.valueChanged.connect(self._update_color_preview)
                g.addWidget(spin, 0, col * 2 + 1)
                self.rgb_spins.append(spin)

            self.swatch = QLabel()
            self.swatch.setFixedSize(90, 44)
            g.addWidget(QLabel("预览:"), 0, 6)
            g.addWidget(self.swatch, 0, 7)

            self.color_name_label = QLabel("--")
            self.color_name_label.setStyleSheet("font-weight:bold;font-size:16px;")
            g.addWidget(QLabel("判定为:"), 1, 0)
            g.addWidget(self.color_name_label, 1, 1, 1, 3)

            self.color_hsl_label = QLabel("--")
            g.addWidget(QLabel("HSL:"), 2, 0)
            g.addWidget(self.color_hsl_label, 2, 1, 1, 5)
            g.setColumnStretch(8, 1)
            calc.setLayout(g)
            lay.addWidget(calc)

            howto = QLabel(
                "怎么用：拿一块真实物料放到相机下 → 从「1 实时监控」或截图读它的 RGB → "
                "填进上面三个框 → 看「判定为」是不是你要的颜色。\n"
                "不对就改下面的阈值；改完到「4 烧录」点 ① 写盘。"
            )
            howto.setWordWrap(True)
            howto.setStyleSheet("color:#555;")
            lay.addWidget(howto)

            warn = QLabel(
                "⚠️ 阈值存在配置文件的 [ColorThresholds] 节。但 color_quant.py 目前是"
                "**硬编码**的 —— 要让这里的值真正生效，需把它的 color_name() 改成读这一节"
                "（协作任务 02）。**在改之前，这里只是「试算 + 记录」，不会改变线上行为。**"
            )
            warn.setWordWrap(True)
            warn.setStyleSheet("color:#a60;")
            lay.addWidget(warn)

            lay.addWidget(QLabel("当前阈值（在「2 参数」区也能改）:"))
            self.th_table = QTableWidget()
            self.th_table.setColumnCount(2)
            self.th_table.setHorizontalHeaderLabels(["键", "值"])
            self.th_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.th_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            lay.addWidget(self.th_table)
            return w

        def _current_thresholds(self) -> dict[str, float]:
            """优先取「2 参数」表里用户改过的值，没有就回默认。"""
            th = {key: default for key, default in COLOR_THRESHOLD_KEYS}
            for r in range(self.param_table.rowCount()):
                sec = self.param_table.item(r, 0)
                key = self.param_table.item(r, 1)
                val = self.param_table.item(r, 2)
                if not (sec and key and val):
                    continue
                if sec.text() == COLOR_SECTION and key.text() in th:
                    try:
                        th[key.text()] = float(val.text())
                    except ValueError:
                        pass
            return th

        def _update_color_preview(self) -> None:
            rgb = tuple(spin.value() for spin in self.rgb_spins)
            name, (h, s, l) = classify_rgb(rgb, self._current_thresholds())
            self.color_name_label.setText(f"{COLOR_CN.get(name, name)}  ({name})")
            self.color_hsl_label.setText(
                f"H={h * 360:.1f}°   S={s:.3f}   L={l:.3f}   RGB={rgb}")
            self.swatch.setStyleSheet(
                f"background-color: rgb({rgb[0]},{rgb[1]},{rgb[2]}); border:1px solid #888;")

        def _refresh_threshold_table(self) -> None:
            th = self._current_thresholds()
            self.th_table.setRowCount(len(COLOR_THRESHOLD_KEYS))
            for r, (key, _) in enumerate(COLOR_THRESHOLD_KEYS):
                self.th_table.setItem(r, 0, QTableWidgetItem(key))
                self.th_table.setItem(r, 1, QTableWidgetItem(str(th[key])))
            self._update_color_preview()

        def _refresh_readiness(self) -> None:
            """上机就绪状态一屏概览 —— 让人一眼看出还差什么才能跑。"""
            n_map = len(self.box_map)
            n_dp = len(self.drop_points)
            rows = [
                ("参数配置", f"{self.param_table.rowCount()} 条",
                 self.param_table.rowCount() > 0),
                ("对应表 (颜色,形状)→货格", f"{n_map} 条", n_map > 0),
                ("六盒落点坐标", f"{n_dp}/6 个", n_dp == 6),
                ("颜色阈值 [ColorThresholds]",
                 "已就绪" if COLOR_SECTION in {
                     self.param_table.item(r, 0).text()
                     for r in range(self.param_table.rowCount())
                     if self.param_table.item(r, 0)} else "缺失",
                 True),
            ]
            self.ready_table.setRowCount(len(rows))
            for r, (name, detail, ok) in enumerate(rows):
                mark = QTableWidgetItem("✅" if ok else "❌")
                mark.setFlags(Qt.ItemIsEnabled)
                self.ready_table.setItem(r, 0, mark)
                for col, txt in ((1, name), (2, detail)):
                    item = QTableWidgetItem(txt)
                    item.setFlags(Qt.ItemIsEnabled)
                    self.ready_table.setItem(r, col, item)

            blockers = []
            if n_dp != 6:
                blockers.append(f"六盒落点差 {6 - n_dp} 个 → run_chain.py 会拒绝启动")
            if n_map == 0:
                blockers.append("对应表为空 → 运行时所有货物都会被拒识")
            self.ready_label.setText(
                "🚧 还不能跑：" + "；".join(blockers) if blockers
                else "✅ 面板侧已就绪。上机前仍需确认：固件可烧录、模型可加载。")
            self.ready_label.setStyleSheet(
                "color:#c00;font-weight:bold;" if blockers else "color:#070;font-weight:bold;")

        # ---------------- 6 屏幕显示 ----------------
        def _build_tab_display(self) -> QWidget:
            """屏幕显示：用 Pi 上的**同一个渲染器**本地出图，快速验证中文/图片/四字段。"""
            w = QWidget()
            lay = QVBoxLayout(w)

            fbox = QGroupBox("中文字体 —— 最重要：字体不对，货物名称会变成方块（＝信息错误＝不得分）")
            fl = QHBoxLayout()
            self.font_input = QLineEdit(find_default_cjk_font())
            self.font_input.textChanged.connect(self._check_font)
            fl.addWidget(self.font_input)
            fb = QPushButton("浏览…")
            fb.clicked.connect(self._pick_font)
            fl.addWidget(fb)
            self.font_state = QLabel("--")
            fl.addWidget(self.font_state)
            fbox.setLayout(fl)
            lay.addWidget(fbox)

            pbox = QGroupBox("要试显示的一条记录（赛题要求 4 个字段全有）")
            g = QGridLayout()
            self.d_seq = QSpinBox(); self.d_seq.setRange(1, 999); self.d_seq.setValue(1)
            self.d_name = QComboBox(); self.d_name.setEditable(True)
            self.d_img = QSpinBox(); self.d_img.setRange(0, 99)
            self.d_count = QSpinBox(); self.d_count.setRange(0, 999); self.d_count.setValue(1)
            self.d_w = QSpinBox(); self.d_w.setRange(320, 4096); self.d_w.setValue(DISPLAY_DEFAULT_W)
            self.d_h = QSpinBox(); self.d_h.setRange(240, 4096); self.d_h.setValue(DISPLAY_DEFAULT_H)
            g.addWidget(QLabel("序号:"), 0, 0); g.addWidget(self.d_seq, 0, 1)
            g.addWidget(QLabel("货物名称:"), 0, 2); g.addWidget(self.d_name, 0, 3, 1, 3)
            g.addWidget(QLabel("图片ID:"), 1, 0); g.addWidget(self.d_img, 1, 1)
            g.addWidget(QLabel("累计数:"), 1, 2); g.addWidget(self.d_count, 1, 3)
            g.addWidget(QLabel("分辨率:"), 1, 4); g.addWidget(self.d_w, 1, 5)
            g.addWidget(QLabel("×"), 1, 6); g.addWidget(self.d_h, 1, 7)
            g.setColumnStretch(8, 1)
            pbox.setLayout(g)
            lay.addWidget(pbox)

            bar = QHBoxLayout()
            rb = QPushButton("🖼 渲染预览")
            rb.clicked.connect(self._render_preview)
            bar.addWidget(rb)
            eb = QPushButton("导出名称表 JSON")
            eb.clicked.connect(self._export_names)
            bar.addWidget(eb)
            cb = QPushButton("生成 run_chain 启动命令")
            cb.clicked.connect(self._gen_run_cmd)
            bar.addWidget(cb)
            bar.addStretch()
            lay.addLayout(bar)

            self.preview_label = QLabel("按「渲染预览」看效果（复用的是树莓派上的同一个渲染器）")
            self.preview_label.setAlignment(Qt.AlignCenter)
            self.preview_label.setMinimumHeight(320)
            self.preview_label.setStyleSheet("background:#111;color:#888;border:1px solid #333;")
            lay.addWidget(self.preview_label)

            il = QHBoxLayout()
            il.addWidget(QLabel("图片目录:"))
            self.imgdir_input = QLineEdit()
            self.imgdir_input.textChanged.connect(self._check_imgdir)
            il.addWidget(self.imgdir_input)
            ib = QPushButton("浏览…")
            ib.clicked.connect(self._pick_image_dir)
            il.addWidget(ib)
            self.imgdir_state = QLabel("--")
            il.addWidget(self.imgdir_state)
            lay.addLayout(il)

            hint = QLabel("图片文件名必须是 <图片ID>.png / .jpg / .jpeg / .webp / .bmp"
                          "（这是 run_chain.py 的 build_image_loader 的约定）。"
                          "目录为空时会用占位色块，预览仍然可用。")
            hint.setWordWrap(True)
            hint.setStyleSheet("color:#555;")
            lay.addWidget(hint)

            lay.addWidget(QLabel("货物名称表（class_id = 形状ID → 屏幕显示的名称）:"))
            self.names_table = QTableWidget()
            self.names_table.setColumnCount(3)
            self.names_table.setHorizontalHeaderLabels(["形状ID", "形状", "显示名称"])
            self.names_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.names_table.setRowCount(len(SHAPE_VOCAB))
            defaults = default_display_names()
            for i, shape in enumerate(SHAPE_VOCAB):
                for col, txt in ((0, str(i)), (1, SHAPE_CN[shape])):
                    it = QTableWidgetItem(txt)
                    it.setFlags(Qt.ItemIsEnabled)
                    self.names_table.setItem(i, col, it)
                self.names_table.setItem(i, 2, QTableWidgetItem(defaults[i]))
            lay.addWidget(self.names_table)

            self._check_font()
            self._check_imgdir()
            self._refresh_name_combo()
            return w

        def _refresh_display_from_text(self, text: str) -> None:
            """把 ini 里的 [DisplayNames] / [Display] 反映到屏幕区控件上。"""
            cfg = configparser.ConfigParser()
            if text:
                try:
                    cfg.read_string(text)
                except configparser.Error:
                    cfg = configparser.ConfigParser()
            names = parse_display_names(cfg)
            for i in range(len(SHAPE_VOCAB)):
                item = self.names_table.item(i, 2)
                if item is None:
                    item = QTableWidgetItem(names[i])
                    self.names_table.setItem(i, 2, item)
                else:
                    item.setText(names[i])
            if cfg.has_section(DISPLAY_SECTION):
                font = cfg.get(DISPLAY_SECTION, "font_path", fallback="").strip()
                imgdir = cfg.get(DISPLAY_SECTION, "image_dir", fallback="").strip()
                if font:
                    self.font_input.setText(font)
                if imgdir:
                    self.imgdir_input.setText(imgdir)
            self._refresh_name_combo()

        def _font_status(self) -> tuple[bool, str]:
            path = self.font_input.text().strip()
            if not path:
                return False, "❌ 未设置 → 中文会变方块"
            if not Path(path).exists():
                return False, "❌ 文件不存在"
            if font_renders_cjk(path):
                return True, "✅ 可渲染中文"
            return False, "❌ 该字体不含中文 → 会变方块"

        def _check_font(self) -> None:
            ok, msg = self._font_status()
            self.font_state.setText(msg)
            self.font_state.setStyleSheet(
                "color:#070;font-weight:bold;" if ok else "color:#c00;font-weight:bold;")

        def _check_imgdir(self) -> None:
            d = self.imgdir_input.text().strip()
            if not d:
                self.imgdir_state.setText("未设置（预览用占位图）")
                self.imgdir_state.setStyleSheet("color:#a60;")
                return
            p = Path(d)
            if not p.is_dir():
                self.imgdir_state.setText("❌ 目录不存在")
                self.imgdir_state.setStyleSheet("color:#c00;font-weight:bold;")
                return
            n = sum(1 for f in p.iterdir()
                    if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"))
            self.imgdir_state.setText(f"✅ {n} 张图")
            self.imgdir_state.setStyleSheet(
                "color:#070;font-weight:bold;" if n else "color:#a60;font-weight:bold;")

        def _refresh_name_combo(self) -> None:
            cur = self.d_name.currentText()
            self.d_name.clear()
            for i, shape in enumerate(SHAPE_VOCAB):
                self.d_name.addItem(self._name_for(i))
            if cur:
                self.d_name.setCurrentText(cur)

        def _name_for(self, idx: int) -> str:
            it = self.names_table.item(idx, 2) if hasattr(self, "names_table") else None
            if it and it.text().strip():
                return it.text().strip()
            return SHAPE_CN[SHAPE_VOCAB[idx]]

        def _pick_font(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择中文字体", "", "字体 (*.ttf *.ttc *.otf);;全部 (*)")
            if path:
                self.font_input.setText(path)

        def _pick_image_dir(self) -> None:
            path = QFileDialog.getExistingDirectory(self, "选择图片目录")
            if path:
                self.imgdir_input.setText(path)

        def _render_preview(self) -> None:
            try:
                src = str(repo_root() / "电控" / "src")
                if src not in sys.path:
                    sys.path.insert(0, src)
                from electrical_control.rpi.display import DisplayViewModel
                from electrical_control.rpi.display_hdmi import HdmiDisplayRenderer
            except Exception as exc:
                QMessageBox.critical(
                    self, "导入失败",
                    f"无法导入树莓派的渲染器：\n{exc}\n\n"
                    "面板复用的是 Pi 上的**同一个**渲染器（HdmiDisplayRenderer），"
                    "所以需要能 import electrical_control。")
                self.say(f"渲染器导入失败: {exc}")
                return

            img_dir = Path(self.imgdir_input.text().strip()) if self.imgdir_input.text().strip() else None

            def loader(image_id: int):
                from PIL import Image
                if img_dir and img_dir.is_dir():
                    for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                        cand = img_dir / f"{image_id}{ext}"
                        if cand.is_file():
                            return Image.open(cand)
                return Image.new("RGB", (400, 320), (198, 120, 62))  # 占位图

            renderer = HdmiDisplayRenderer(
                width=self.d_w.value(),
                height=self.d_h.value(),
                image_loader=loader,
                frame_output=lambda _f: None,
                font_path=self.font_input.text().strip() or None,
                # _compose_frame() 不使用 task；这里只做预览，不走完整 present()/PendingRender
                task=None,
            )
            view = DisplayViewModel(
                target_seq=self.d_seq.value(),
                name=self.d_name.currentText(),
                image_id=self.d_img.value(),
                success_count=self.d_count.value(),
                result_code=0,
            )
            try:
                frame = renderer._compose_frame(view)
            except Exception as exc:
                QMessageBox.critical(self, "渲染失败", str(exc))
                self.say(f"渲染失败: {exc}")
                return

            rgb = frame.convert("RGB")
            qimg = QImage(rgb.tobytes("raw", "RGB"), rgb.width, rgb.height,
                          rgb.width * 3, QImage.Format_RGB888)
            pix = QPixmap.fromImage(qimg)
            self.preview_label.setPixmap(pix.scaled(
                max(self.preview_label.width(), 640),
                max(self.preview_label.height(), 320),
                Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.preview_label.setStyleSheet("background:#000;border:1px solid #333;")
            ok, msg = self._font_status()
            self.say(f"已渲染预览 {rgb.width}×{rgb.height}（与树莓派同一渲染器）｜字体: {msg}")
            if not ok:
                self.say("⚠️ 字体不支持中文 —— 截图里的货物名称会是方块，请换字体")

        def _collect_names(self) -> dict[int, str]:
            return {i: self._name_for(i) for i in range(len(SHAPE_VOCAB))}

        def _export_names(self) -> None:
            names = self._collect_names()
            payload = {str(k): v for k, v in names.items()}
            out = repo_root() / "工具" / "generated_names.json"
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.say(f"已导出名称表 → {out}（这就是 --names-file 的格式）")
            QMessageBox.information(
                self, "已导出",
                f"名称表已写到:\n{out}\n\n"
                f"启动时加参数：--names-file {out}")
            return

        def _gen_run_cmd(self) -> None:
            font = self.font_input.text().strip() or "<中文字体路径>"
            names = repo_root() / "工具" / "generated_names.json"
            imgdir = self.imgdir_input.text().strip() or "<图片目录>"
            cmd = (
                "python3 run_chain.py \\\n"
                "  --port /dev/ttyAMA0 --baud 115200 \\\n"
                "  --round-id <本轮ID> --round-task-id <本轮任务号> \\\n"
                f'  --config /home/pi/sorting_config.ini \\\n'
                f'  --font "{font}" \\\n'
                f'  --names-file "{names}" \\\n'
                f'  --image-dir "{imgdir}" \\\n'
                "  --frame-output fb0 --start-round\n"
            )
            QApplication.clipboard().setText(cmd)
            self.say("已复制 run_chain 启动命令到剪贴板:\n" + cmd)

        # ---------------- 7 抓取时序 ----------------
        def _build_tab_flow(self) -> QWidget:
            """抓取时序：展示规范 10 步，并读固件真实常量对照报警。"""
            w = QWidget()
            lay = QVBoxLayout(w)

            top = QHBoxLayout()
            rb = QPushButton("重新读取固件常量")
            rb.clicked.connect(self._refresh_flow)
            top.addWidget(rb)
            top.addWidget(QLabel("（读的是 App/Inc/ec_motion_plan.h 里的真实 #define）"))
            top.addStretch()
            lay.addLayout(top)

            self.flow_warn = QLabel("--")
            self.flow_warn.setWordWrap(True)
            lay.addWidget(self.flow_warn)

            lay.addWidget(QLabel("固件里的实际常量:"))
            self.flow_const = QTableWidget()
            self.flow_const.setColumnCount(2)
            self.flow_const.setHorizontalHeaderLabels(["常量", "当前值"])
            self.flow_const.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.flow_const.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.flow_const.setMaximumHeight(170)
            lay.addWidget(self.flow_const)

            lay.addWidget(QLabel(
                "规范抓取时序（10 步）—— 见 docs/design/抓取时序-2026-09-15.md"))
            self.flow_table = QTableWidget()
            self.flow_table.setColumnCount(4)
            self.flow_table.setHorizontalHeaderLabels(["步", "动作", "坐标来源", "固定/变动"])
            self.flow_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.flow_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.flow_table.setRowCount(len(CANONICAL_FLOW))
            for r, row in enumerate(CANONICAL_FLOW):
                for c, txt in enumerate(row):
                    it = QTableWidgetItem(txt)
                    if "变动" in row[3]:
                        it.setForeground(Qt.red)
                    self.flow_table.setItem(r, c, it)
            lay.addWidget(self.flow_table)

            note = QLabel(
                "② 那一步是现在【做不到】的：main.py 是每帧无条件发识别结果，"
                "树莓派不能「请求一张新图」→ 可能拿几帧前的旧坐标去抓 → 抓空。\n"
                "赛题 PDF §4 给的方案是 request_id 握手（属 L4，改协议）。\n"
                "⚠️ 停放位只回 HOME（角落）—— 相机固定在装置中心，夹爪停 (0,0) 会正好挡住镜头。\n"
                "⏳ 挂账（省赛前必做）：物料高度视差补偿 —— 校赛拿实物直接标定即可，"
                "但换物料后该标定失效，必须重标或做分层换算。")
            note.setWordWrap(True)
            note.setStyleSheet("color:#a60;")
            lay.addWidget(note)

            self._refresh_flow()
            return w

        def _refresh_flow(self) -> None:
            hdr = repo_root() / "电控" / "firmware" / "stm32f407_m144z" / "App" / "Inc" / "ec_motion_plan.h"
            consts: dict[str, int] = {}
            if hdr.exists():
                consts = parse_motion_constants(hdr.read_text(encoding="utf-8"))
            rows = sorted(consts.items())
            self.flow_const.setRowCount(len(rows))
            for r, (k, v) in enumerate(rows):
                self.flow_const.setItem(r, 0, QTableWidgetItem(k))
                mm = f"  ({v / 10:.1f} mm)" if k.endswith("MM10") else ""
                self.flow_const.setItem(r, 1, QTableWidgetItem(f"{v}{mm}"))

            warns = check_pick_sequence(consts)
            if not hdr.exists():
                self.flow_warn.setText(f"⚠️ 读不到 {hdr}")
                self.flow_warn.setStyleSheet("color:#a60;font-weight:bold;")
                return
            self.flow_warn.setText("\n".join(warns) if warns else "✅ 与规范时序一致")
            self.flow_warn.setStyleSheet(
                "color:#c00;font-weight:bold;" if any(x.startswith("🔴") for x in warns)
                else "color:#070;font-weight:bold;")

        def _build_tab_flash(self) -> QWidget:
            w = QWidget()
            lay = QVBoxLayout(w)

            readybox = QGroupBox("上机就绪状态")
            rv = QVBoxLayout()
            self.ready_table = QTableWidget()
            self.ready_table.setColumnCount(3)
            self.ready_table.setHorizontalHeaderLabels(["", "项", "现状"])
            self.ready_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.ready_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.ready_table.verticalHeader().setVisible(False)
            rv.addWidget(self.ready_table)
            self.ready_label = QLabel("--")
            self.ready_label.setWordWrap(True)
            rv.addWidget(self.ready_label)
            readybox.setLayout(rv)
            lay.addWidget(readybox)

            pathbox = QGroupBox("目标配置文件")
            pwrap = QVBoxLayout()
            pl = QHBoxLayout()
            self.ini_input = QLineEdit(str(self.ini_path))
            pl.addWidget(self.ini_input)
            browse = QPushButton("浏览…")
            browse.clicked.connect(self.pick_ini)
            pl.addWidget(browse)
            reload_btn = QPushButton("重新载入")
            reload_btn.clicked.connect(self._load_ini)
            pl.addWidget(reload_btn)
            pwrap.addLayout(pl)

            p2 = QHBoxLayout()
            p2.addWidget(QLabel("树莓派地址（生成 scp/ssh 命令用）:"))
            self.pi_host = QLineEdit("172.20.10.8")
            self.pi_host.setMaximumWidth(160)
            p2.addWidget(self.pi_host)
            p2.addStretch()
            pwrap.addLayout(p2)
            pathbox.setLayout(pwrap)
            lay.addWidget(pathbox)

            btns = QGroupBox("动作")
            bl = QVBoxLayout()
            b1 = QPushButton("① 写本地 sorting_config.ini（保留全部注释）")
            b1.clicked.connect(self.flash_local)
            bl.addWidget(b1)

            b2 = QPushButton("② 下发到 MaixCAM（conf/iou，立即生效）")
            b2.clicked.connect(self.push_live_params)
            bl.addWidget(b2)

            b3 = QPushButton("③ 生成树莓派部署命令（复制到剪贴板）")
            b3.clicked.connect(self.make_deploy_cmd)
            bl.addWidget(b3)

            b4 = QPushButton("④ 导出 Python 片段（BoxAssignment + DropTable）")
            b4.clicked.connect(self.export_python)
            bl.addWidget(b4)
            btns.setLayout(bl)
            lay.addWidget(btns)

            honest = QLabel(
                "说明：①② 是真的生效路径。③ 只生成命令，要你在能 ssh 到树莓派的机器上执行。 "
                "④ 是因为对应表和落点表目前还没有生产消费方 —— 导出的片段才是接进运行时的桥梁。"
            )
            honest.setWordWrap(True)
            honest.setStyleSheet("color:#a60;")
            lay.addWidget(honest)

            lay.addWidget(QLabel("日志:"))
            self.log = QTextEdit()
            self.log.setReadOnly(True)
            lay.addWidget(self.log)
            return w

        # ---------------- 日志 ----------------
        def say(self, msg: str) -> None:
            stamp = datetime.now().strftime("%H:%M:%S")
            self.log.append(f"[{stamp}] {msg}")

        # ---------------- INI 读写 ----------------
        def _read_ini_text(self) -> str:
            p = Path(self.ini_input.text()) if hasattr(self, "ini_input") else self.ini_path
            if not p.exists():
                return ""
            return p.read_text(encoding="utf-8")

        def _load_ini(self) -> None:
            self.ini_path = Path(self.ini_input.text()) if hasattr(self, "ini_input") else default_ini()
            if hasattr(self, "ini_input"):
                self.ini_input.setText(str(self.ini_path))
            text = self._read_ini_text()
            if not text:
                self.say(f"配置文件不存在或为空: {self.ini_path}")
                self.box_map = {}
                self.drop_points = {}
            else:
                cfg = configparser.ConfigParser()
                cfg.read_string(text)
                self.box_map = parse_box_map(cfg)
                self.drop_points = parse_drop_points(cfg)
                if cfg.has_section("Vision"):
                    conf = cfg.get("Vision", "confidence_threshold",
                                   fallback=cfg.get("Vision", "conf_threshold", fallback="0.5"))
                    iou = cfg.get("Vision", "iou_threshold", fallback="0.45")
                    self.conf_slider.setValue(int(float(conf) * 100))
                    self.iou_slider.setValue(int(float(iou) * 100))
                self._refresh_param_table(text)
                self.say(f"已载入 {self.ini_path}：参数 {self.param_table.rowCount()} 条，"
                         f"对应表 {len(self.box_map)} 条，落点 {len(self.drop_points)} 个")
            self._refresh_map_table()
            self._refresh_drop_table()
            self._refresh_issues()
            self._refresh_threshold_table()
            self._refresh_readiness()
            self._refresh_display_from_text(text)

        def _refresh_param_table(self, text: str) -> None:
            rows = parse_scalar_params(text) if text else []
            # 配置里还没有 [ColorThresholds] 时，用默认值补进来。
            # 否则「5 颜色标定」区改的阈值无处存放，写盘只会写回默认值（踩过）。
            if COLOR_SECTION not in {sec for sec, _, _ in rows}:
                rows += [(COLOR_SECTION, key, str(val))
                         for key, val in COLOR_THRESHOLD_KEYS]
            self.param_table.setRowCount(len(rows))
            for r, (sec, key, val) in enumerate(rows):
                for col, txt in enumerate((sec, key, val)):
                    item = QTableWidgetItem(txt)
                    if col < 2:
                        item.setFlags(Qt.ItemIsEnabled)
                    self.param_table.setItem(r, col, item)

        def _collect_drop_points(self) -> dict[int, tuple[float, float]]:
            out: dict[int, tuple[float, float]] = {}
            for r, b in enumerate(BOX_IDS):
                x = self.dp_table.cellWidget(r, 1).value()
                y = self.dp_table.cellWidget(r, 2).value()
                if x != 0.0 or y != 0.0:
                    out[b] = (x, y)
            return out

        # ---------------- 对应表 ----------------
        def add_mapping(self) -> None:
            c = self.color_combo.currentData()
            s = self.shape_combo.currentData()
            b = self.box_combo.currentData()
            old = self.box_map.get((c, s))
            self.box_map[(c, s)] = b
            act = f"覆盖（原 {old} 号）" if old is not None else "新增"
            self.say(f"{act}: ({COLOR_CN[COLOR_VOCAB[c]]}, {SHAPE_CN[SHAPE_VOCAB[s]]}) → {b} 号货格")
            self._refresh_map_table()
            self._refresh_issues()

        def remove_mapping(self, c: int, s: int) -> None:
            if self.box_map.pop((c, s), None) is not None:
                self.say(f"删除: ({COLOR_CN[COLOR_VOCAB[c]]}, {SHAPE_CN[SHAPE_VOCAB[s]]})")
            self._refresh_map_table()
            self._refresh_issues()

        def _refresh_map_table(self) -> None:
            items = sorted(self.box_map.items())
            self.map_table.setRowCount(len(items))
            for r, ((c, s), b) in enumerate(items):
                self.map_table.setItem(r, 0, QTableWidgetItem(f"{COLOR_CN[COLOR_VOCAB[c]]} ({c})"))
                self.map_table.setItem(r, 1, QTableWidgetItem(f"{SHAPE_CN[SHAPE_VOCAB[s]]} ({s})"))
                self.map_table.setItem(r, 2, QTableWidgetItem(f"{b} 号"))
                btn = QPushButton("删除")
                btn.clicked.connect(lambda _, cc=c, ss=s: self.remove_mapping(cc, ss))
                self.map_table.setCellWidget(r, 3, btn)

        def _refresh_drop_table(self) -> None:
            for r, b in enumerate(BOX_IDS):
                if b in self.drop_points:
                    x, y = self.drop_points[b]
                    self.dp_table.cellWidget(r, 1).setValue(x)
                    self.dp_table.cellWidget(r, 2).setValue(y)

        def _refresh_issues(self) -> None:
            self.drop_points = self._collect_drop_points()
            errs, warns = validate(self.box_map, self.drop_points)
            parts = []
            if errs:
                parts.append("❌ 阻断烧录:\n  - " + "\n  - ".join(errs))
            if warns:
                parts.append("⚠️ 注意:\n  - " + "\n  - ".join(warns))
            if not parts:
                parts.append("✅ 对应表与落点表校验通过。")
            self.issues_label.setText("\n".join(parts))
            self.issues_label.setStyleSheet("color:#c00;" if errs else "color:#070;")
            self._refresh_readiness()

        # ---------------- 烧录 ----------------
        def flash_local(self) -> None:
            self.drop_points = self._collect_drop_points()
            errs, warns = validate(self.box_map, self.drop_points)
            if errs:
                QMessageBox.critical(self, "校验未通过", "先修好这些问题再烧录：\n\n" + "\n".join(errs))
                self.say("烧录被阻断：校验未通过")
                return

            p = Path(self.ini_input.text())
            text = p.read_text(encoding="utf-8") if p.exists() else ""
            if not text:
                QMessageBox.warning(self, "没有配置文件",
                                    f"{p} 不存在。请把它先放到这个路径，或改用浏览选择树莓派上的那份。")
                return

            backup = p.with_suffix(p.suffix + ".bak")
            shutil.copy2(p, backup)

            changed = 0
            for r in range(self.param_table.rowCount()):
                sec_item = self.param_table.item(r, 0)
                key_item = self.param_table.item(r, 1)
                val_item = self.param_table.item(r, 2)
                if not (sec_item and key_item and val_item):
                    continue
                new_text = set_ini_value(text, sec_item.text(), key_item.text(), val_item.text())
                if new_text != text:
                    changed += 1
                    text = new_text

            text = upsert_section(text, COLOR_SECTION,
                                  format_color_thresholds(self._current_thresholds()))
            text = upsert_section(text, DISPLAY_NAMES_SECTION,
                                  format_display_names(self._collect_names()))
            text = upsert_section(text, BOXMAP_SECTION, format_box_map(self.box_map))
            text = upsert_section(text, DROPPOINTS_SECTION, format_drop_points(self.drop_points))
            p.write_text(text, encoding="utf-8")

            for wmsg in warns:
                self.say(f"⚠️ {wmsg}")
            self.say(f"✅ 已写入 {p}（备份 {backup.name}）")
            self.say(f"   参数 {changed} 条，对应表 {len(self.box_map)} 条，"
                     f"落点 {len(self.drop_points)} 个")
            QMessageBox.information(self, "已写入", f"已写入:\n{p}\n\n备份:\n{backup.name}")

        def push_live_params(self) -> None:
            if not self.connected:
                QMessageBox.warning(self, "未连接", "先在上方连接 MaixCAM。")
                return
            cmd = {
                "type": "UPDATE_PARAMS",
                "conf_th": self.conf_slider.value() / 100,
                "iou_th": self.iou_slider.value() / 100,
            }
            try:
                self.sock.sendall(json.dumps(cmd).encode() + b"\n")
            except Exception as exc:
                QMessageBox.critical(self, "发送失败", str(exc))
                self.say(f"下发失败: {exc}")
                return
            self.say(f"已下发 MaixCAM: conf={cmd['conf_th']:.2f} iou={cmd['iou_th']:.2f}")
            QMessageBox.information(self, "已下发", "参数已发送，MaixCAM 立即生效。")

        def make_deploy_cmd(self) -> None:
            ini = self.ini_input.text()
            host = self.pi_host.text() or "172.20.10.8"
            cmd = (
                f'scp "{ini}" pi@{host}:/home/pi/sorting_config.ini\n'
                f'ssh pi@{host} "sudo python3 /home/pi/apply_config.py"\n'
            )
            QApplication.clipboard().setText(cmd)
            self.say("已复制部署命令到剪贴板:\n" + cmd)

        def export_python(self) -> None:
            self.drop_points = self._collect_drop_points()
            errs, _ = validate(self.box_map, self.drop_points)
            if errs:
                QMessageBox.critical(self, "校验未通过", "\n".join(errs))
                return
            lines = [
                "from sorting_vision.sort_plan import BoxAssignment",
                "from sorting_vision.drop_table import DropTable, DropPoint",
                "",
                "BOX_ASSIGNMENT = BoxAssignment({",
            ]
            for (c, s), b in sorted(self.box_map.items()):
                lines.append(f"    ({c}, {s}): {b},   # {COLOR_CN[COLOR_VOCAB[c]]}"
                             f" {SHAPE_CN[SHAPE_VOCAB[s]]} -> {b} 号")
            lines.append("})")
            lines.append("")
            lines.append("DROP_TABLE = DropTable({")
            for b, (x, y) in sorted(self.drop_points.items()):
                lines.append(f"    {b}: DropPoint({int(round(x * 10))}, {int(round(y * 10))}),")
            lines.append("})")
            snippet = "\n".join(lines) + "\n"
            out = repo_root() / "工具" / "generated_params.py"
            out.write_text(snippet, encoding="utf-8")
            self.say(f"已导出 {out}")

        def pick_ini(self) -> None:
            path, _ = QFileDialog.getOpenFileName(self, "选择 sorting_config.ini", "", "INI (*.ini);;全部 (*)")
            if path:
                self.ini_input.setText(path)
                self._load_ini()

        # ---------------- 连接 ----------------
        def toggle_connection(self) -> None:
            if self.connected:
                self.disconnect()
            else:
                self.connect()

        def connect(self) -> None:
            try:
                host = self.ip_input.text().strip()
                port = int(self.port_input.text().strip())
                self.sock = open_socket(host, port)
            except Exception as exc:
                QMessageBox.critical(self, "连接失败", str(exc))
                self.say(f"连接失败: {exc}")
                self.disconnect()
                return

            self.connected = True
            self.status_label.setText("已连接")
            self.status_label.setStyleSheet("color:#070;font-weight:bold;")
            self.connect_btn.setText("断开")
            self.push_live_btn.setEnabled(True)
            self.shot_btn.setEnabled(True)

            self.recv_thread = RecvThread(self.sock)
            self.recv_thread.data_received.connect(self.on_data)
            self.recv_thread.connection_lost.connect(self.on_lost)
            self.recv_thread.start()
            self.stall_timer.start(1000)
            self.say(f"已连接 {host}:{port}")

        def disconnect(self) -> None:
            self.stall_timer.stop()
            if self.recv_thread:
                self.recv_thread.stop()
                self.recv_thread.wait(1000)
                self.recv_thread = None
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
            self.connected = False
            self.status_label.setText("未连接")
            self.status_label.setStyleSheet("color:#c00;font-weight:bold;")
            self.connect_btn.setText("连接")
            self.push_live_btn.setEnabled(False)
            self.shot_btn.setEnabled(False)

        def on_lost(self) -> None:
            self.say("连接断开")
            self.disconnect()
            self.stall_label.setText("连接已断开")
            self.stall_label.setStyleSheet("color:#c00;font-weight:bold;")

        def on_data(self, data: dict) -> None:
            self.last_frame_at = datetime.now()
            self.fps_label.setText(f"{data.get('fps', 0.0):.1f}")
            dets = data.get("detections", [])
            self.det_label.setText(str(len(dets)))
            self.frame_at_label.setText(self.last_frame_at.strftime("%H:%M:%S"))
            self.stall_label.setText("正常")
            self.stall_label.setStyleSheet("color:#070;font-weight:bold;")

            self.det_table.setRowCount(len(dets))
            for i, d in enumerate(dets):
                self.det_table.setItem(i, 0, QTableWidgetItem(str(d.get("class_id", "?"))))
                self.det_table.setItem(i, 1, QTableWidgetItem(str(d.get("class_name", "?"))))
                self.det_table.setItem(i, 2, QTableWidgetItem(f"{d.get('confidence', 0.0):.2f}"))
                center = d.get("center") or [0, 0]
                self.det_table.setItem(i, 3, QTableWidgetItem(str(center[0])))
                self.det_table.setItem(i, 4, QTableWidgetItem(str(center[1])))

        def _check_stall(self) -> None:
            if not self.connected or self.last_frame_at is None:
                return
            gap = (datetime.now() - self.last_frame_at).total_seconds()
            if gap > STALL_WARN_SEC:
                self.stall_label.setText(f"⚠️ {gap:.0f} 秒没有新帧")
                self.stall_label.setStyleSheet("color:#c00;font-weight:bold;")

        def save_screenshot(self) -> None:
            if not self.connected:
                return
            try:
                self.sock.sendall(json.dumps({"type": "SAVE_SCREENSHOT"}).encode() + b"\n")
                self.say("已发送截图命令")
            except Exception as exc:
                self.say(f"截图命令失败: {exc}")

        # ---------------- 9002 全链路（树莓派广播） ----------------
        def pi_say(self, msg: str) -> None:
            stamp = datetime.now().strftime("%H:%M:%S")
            self.pi_log.append(f"[{stamp}] {msg}")
            # ponytail: 只留最近 200 行；长时间跑不会把内存吃满
            lines = self.pi_log.toPlainText().splitlines()
            if len(lines) > 200:
                self.pi_log.setPlainText("\n".join(lines[-200:]))

        def toggle_pi(self) -> None:
            if self.connected2:
                self.disconnect_pi()
            else:
                self.connect_pi()

        def connect_pi(self) -> None:
            try:
                host = self.ip2_input.text().strip()
                port = int(self.port2_input.text().strip())
                self.sock2 = open_socket(host, port)
            except Exception as exc:
                QMessageBox.critical(self, "连接失败", str(exc))
                self.disconnect_pi()
                return

            self.connected2 = True
            self.status2_label.setText("已连接")
            self.status2_label.setStyleSheet("color:#070;font-weight:bold;")
            self.connect2_btn.setText("断开")
            self.recv_thread2 = RecvThread(self.sock2)
            self.recv_thread2.data_received.connect(self.on_pi_data)
            self.recv_thread2.connection_lost.connect(self.on_pi_lost)
            self.recv_thread2.start()
            self.pi_say(f"已连接 {host}:{port}")

        def disconnect_pi(self) -> None:
            if self.recv_thread2:
                self.recv_thread2.stop()
                self.recv_thread2.wait(1000)
                self.recv_thread2 = None
            if self.sock2:
                try:
                    self.sock2.close()
                except Exception:
                    pass
                self.sock2 = None
            self.connected2 = False
            self.status2_label.setText("未连接")
            self.status2_label.setStyleSheet("color:#c00;font-weight:bold;")
            self.connect2_btn.setText("连接")

        def on_pi_lost(self) -> None:
            self.pi_say("连接断开")
            self.disconnect_pi()

        def on_pi_data(self, data: dict) -> None:
            self.last2_label.setText(datetime.now().strftime("%H:%M:%S"))

            vision = data.get("vision")
            if vision:
                task_id = vision.get("task_id", "--")
                targets = vision.get("targets", [])
                self.v_task.setText(str(task_id))
                self.v_count.setText(str(len(targets)))
                self.v_stage.setText("✅ 已收到")
                self.v_stage.setStyleSheet("color:#070;font-weight:bold;")
                self.pi_vision_table.setRowCount(len(targets))
                for i, t in enumerate(targets):
                    self.pi_vision_table.setItem(
                        i, 0, QTableWidgetItem(str(t.get("target_seq", ""))))
                    self.pi_vision_table.setItem(
                        i, 1, QTableWidgetItem(str(t.get("class_id", ""))))
                    self.pi_vision_table.setItem(
                        i, 2, QTableWidgetItem(str(t.get("box_id", ""))))
                self.pi_say(f"视觉批次 task_id={task_id}，{len(targets)} 个目标")

            task = data.get("item_task")
            if task:
                self.c_stage.setText("✅ 已发出")
                self.c_stage.setStyleSheet("color:#070;font-weight:bold;")
                self.c_ids.setText(f"{task.get('round_id', '--')} / {task.get('task_id', '--')}")
                self.c_target.setText(
                    f"#{task.get('target_seq', '--')} 类{task.get('class_id', '--')}")
                self.c_x.setText(str(task.get("x_position", "--")))
                self.c_y.setText(str(task.get("y_position", "--")))
                self.pi_say(f"电控指令 目标#{task.get('target_seq')} "
                            f"x={task.get('x_position')} y={task.get('y_position')}")

            result = data.get("item_result")
            if result:
                ok = bool(result.get("success", False))
                self.r_stage.setText("✅ 成功" if ok else "❌ 失败")
                self.r_stage.setStyleSheet("color:#070;font-weight:bold;" if ok
                                           else "color:#c00;font-weight:bold;")
                self.r_result.setText("成功" if ok else "失败")
                self.r_code.setText(f"0x{result.get('result_code', 0):02X} / "
                                    f"0x{result.get('basis', 0):02X}")
                self.pi_say(f"执行结果 目标#{result.get('target_seq')} "
                            f"{'成功' if ok else '失败'}")

        def closeEvent(self, event) -> None:
            self.disconnect()
            self.disconnect_pi()
            event.accept()


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    app = QApplication(sys.argv)
    win = ControlPanel()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
