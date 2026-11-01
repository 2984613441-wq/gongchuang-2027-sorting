"""落料位颜色判决（2026-11-01 新增）：

副相机（DF200，USB 接在树莓派上）在**落料位**抓一帧，用 Pi 本地 OpenCV 判颜色，
再和三态判决配合决定「放下去的到底是不是我们以为的那件」。

为什么判颜色而不是判 code（形状+颜色）
--------------------------------------
* 形状在主相机（YOLO11n 6 类，mAP50 0.978）**抓取前**已经判过，且抓的是同一件；
* 树莓派没有 YOLO 推理运行时（`cv2 4.5.1` 的 DNN 不支持 YOLO11 的 attention，
  也没有 onnxruntime），在落料位再判形状要另建通道（电脑侧/相机侧），成本高、节拍紧；
* 混料的**主要来源是颜色**（同形状不同颜色放错格），颜色校验性价比最高。

边界
----
* 纯函数：输入一个 HSV 值（cv2 口径），输出 color_id(1..5) 或 0（判不出）。
* 不抓帧、不开相机、不发串口；取帧与 ROI 裁剪在 `place_eye.py`（另建）。
* 阈值全部【待实测】：必须在**固定补光灯 + 锁定曝光/AWB**下标定。

cv2 口径提醒：`cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)` 得到 H∈[0,179]、
S∈[0,255]、V∈[0,255]（注意 H 是 OpenCV 的 0..179，不是 0..360）。
"""

from __future__ import annotations

__all__ = [
    "COLOR_NAMES",
    "hsv_to_color",
    "infer_code_from_color",
    "shape_from_code",
]

#: color_id → 名称（1..5 与协议 V1.0 一致）
COLOR_NAMES = {1: "red", 2: "yellow", 3: "green", 4: "blue", 5: "white"}

#: 颜色阈值（cv2 HSV 口径，H 0..179）—— 全部【待实测】
#: 结构：color_id -> (h_lo, h_hi, s_min, v_min, v_max)
#: 红色跨 0 界，故用两段（h_lo > h_hi 表示跨 0）。
THRESHOLDS: dict[int, tuple[int, int, int, int, int]] = {
    1: (0, 10, 90, 60, 255),      # red：h∈[0,10] 或 [170,179]
    2: (11, 28, 80, 80, 255),     # yellow
    3: (29, 80, 60, 60, 255),     # green
    4: (81, 130, 80, 50, 255),    # blue
    5: (0, 179, 0, 170, 255),     # white：低饱和 + 高亮（S 上限见 s_max）
}
#: 白色的饱和度上限（其它颜色不看这个）
WHITE_S_MAX = 60


def hsv_to_color(h: int, s: int, v: int) -> int:  # noqa: PLR0911
    """cv2 HSV → color_id(1..5)；判不出返回 0。阈值【待实测】。"""
    h = int(h) % 180
    s = max(0, min(255, int(s)))
    v = max(0, min(255, int(v)))

    if v < 40:
        return 0                                   # 太暗，任何颜色都不可信
    if s < WHITE_S_MAX and v >= 170:
        return 5                                   # white
    if s < 60:
        return 0                                   # 灰/暗灰，不猜

    for color in (1, 2, 3, 4):
        lo, hi, s_min, v_min, v_max = THRESHOLDS[color]
        if s < s_min or v < v_min or v > v_max:
            continue
        if color == 1:                             # 红色跨 0 界
            if h <= lo or h >= 170:
                return 1
        elif lo <= h <= hi:
            return color
    return 0


def shape_from_code(code: int) -> int | None:
    """code(1..30) → shape(1..6)；非法返回 None。"""
    code = int(code)
    if not (1 <= code <= 30):
        return None
    return (code - 1) // 5 + 1


def infer_code_from_color(expected_code: int, observed_color: int) -> int | None:
    """颜色复看不符时，按「形状不变、颜色换成观测值」推断实际 code。

    仅当 ``observed_color`` 合法且 ``expected_code`` 合法时返回，否则 None。
    调用方必须把结果标成 **推断值**（不是观测值），因为形状没有复看。
    """
    shape = shape_from_code(expected_code)
    observed_color = int(observed_color)
    if shape is None or not (1 <= observed_color <= 5):
        return None
    return (shape - 1) * 5 + observed_color
