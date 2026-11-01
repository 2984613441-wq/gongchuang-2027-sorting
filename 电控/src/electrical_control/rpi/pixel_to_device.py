"""像素坐标 → 装置坐标转换模块（带高度视差补偿）

设计依据：docs/审核v2.0.md §1-§4 (W6 标定链设计)

转换流程：
  0. 像素域检查：只接受标定覆盖的 [57,232]×[142,232]
  1. 仿射变换：像素 (u,v) → 顶面装置坐标 (x_top, y_top) mm
  2. 高度视差补偿：(x_top, y_top) → 底面 (x_bottom, y_bottom) mm
     scale = camera_height / (camera_height - object_height)
     bottom = nadir + (top - nadir) * scale
     nadir = 图像中心的仿射像（当前 320×320 图像为 (160,160)）
  3. 边界检查：超出配置工作区 → 返回 None
  4. 单位转换：mm → 0.1mm (协议单位)

工具偏移不属于相机标定，由 make_grasp_point_for_target 在本函数结果之后应用。

fail-closed 原则：
  - 未标定 → 所有转换返回 None
  - 超出工作区 → 返回 None
  - 物体高度缺失或非法 → 返回 None（只有显式 h=0 才不补偿）
  - 配置文件缺失 → 未标定状态

⚠️ 未验证声明：
  - 所有数值（仿射参数、相机高度、物体高度）需实测后填入
  - 误差预算基于理论计算，实际精度需九宫格验证
  - 本模块不改 BATCH_TARGETS 字段语义（X/Y 仍是像素）
"""

from __future__ import annotations

import configparser
import logging
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    from electrical_control.rpi.vision_ingest import GraspPointForTarget, VisionTarget

_LOGGER = logging.getLogger(__name__)

# 标定实际覆盖的像素域。域外点没有标定约束，继续套仿射矩阵只是线性外推，
# 不是测量；必须 fail-closed。
#
# 🔴 2026-09-19 重新标定后更新（原值 (57,232)x(142,232) 属 2026-09-18 粗标）。
#    旧值把 py<142 的点全部拒掉，而新标定的实测锚点 py 一路低到 96
#    → 物块正常摆放也会被判"像素域外"，整链一件都出不来。
#    下列范围取自 2026-09-19 标定中【已由用户目视或尺子确认】的像素点：
#      (72, 96)↔(105.0,12.5)   (70,138)↔(85.0,12.5)   (134,103)↔(105.0,-17.5)
#      (99,188)↔(62.3,-4.6)    (92,211)↔(50.8,-2.3)   (160,239)↔(40.5,-36.5)
#      (191,111)↔(103.8,-45.4) (206,135)↔(92.9,-53.8)  (158,160)=光轴
#    px 跨 70~206、py 跨 96~239；下面各留 ~10px 余量。
#    ⚠️ 再次重新标定后必须同步更新此处，否则又会变成新的误杀源。
#
# 🔴 2026-09-19 二改：(60,240)x(85,270) → 整帧 (15,305)x(15,305)。
#    【为什么改】用户要求：**只要物块在托盘上、且在相机识别区内，机械就必须能抓**。
#    但 2026-09-19 实机跑链时，用户现场摆的两个物块**两个都被本门禁拒掉**：
#      pixel=(168, 77)  → py=77 < 85，被"像素域外"拒
#      pixel=(293, 230) → px=293 > 240，被"像素域外"拒
#    第一个的手算 PICK=(−1.3, −76.2)mm **完全在可达域内**，只差 8px 就被误杀。
#    ⇒ 本门禁当时是"夹取范围远小于识别范围"的**直接成因**，必须放开。
#
#    【改后的定位：本门禁不再承担"标定域"语义，它只是"整帧有效区"边界】
#    真正的安全网是**工作区校验**（本文件 :472-488），它校验【叠加 ToolOffset 后的
#    最终 PICK】是否落在 [WorkspaceLimits] 内。够不到的点在那里被拒，且拒识原因
#    会明确写出 PICK 坐标 —— 比"像素域外"可诊断得多。
#
#    【代价与欠账（必须记住）】
#    仿射只在 px 70~206 / py 96~239 上有实测锚点；越出该区是**线性外推**，
#    对针孔相机成立、对镜头畸变不成立。当前标定自评"两轴比例一致 ⇒ 镜无畸变"，
#    故外推可接受；但**正式九点标定铺满全帧后，本门禁应重新收紧到实测覆盖区**，
#    那时的收紧才是"有测量支撑"的收紧，不是现在这种"照小块标定画地为牢"。
_CALIBRATED_PIXEL_X_LIMITS = (15.0, 305.0)
_CALIBRATED_PIXEL_Y_LIMITS = (15.0, 305.0)

# 🔴🔴 2026-10-29 分辨率迁移（320×320 → 1280×720）
#
# 背景：视觉链路原本按 **320×320** 输出像素，上面两个常量就是那个时代定的。
# 现在 MaixCAM 采集/上报改成 **1280×720**（v11 模型训练用的也是 1280×720），
# 结果 1280 域的像素（如 (118,477)）被 `[15,305]` 判成"像素域外"，
# 整批件一件都换算不出来（实测：2026-10-29 23:30 p_look2 全被判域外）。
#
# 处置：把"有效像素区间"改成**相对帧尺寸的比例**（原 15/320、305/320），
# 这样换分辨率不用改常量。
# 兼容性：frame=320×320 时算出来就是 (15,305)，与旧行为**逐值相同**。
_PIXEL_DOMAIN_LO_RATIO = 15.0 / 320.0
_PIXEL_DOMAIN_HI_RATIO = 305.0 / 320.0


def pixel_domain_limits(frame_w: float, frame_h: float):
    """按帧尺寸算「有效像素区间」。

    Returns:
        ((ux_lo, ux_hi), (vy_lo, vy_hi))
    """
    return (
        (_PIXEL_DOMAIN_LO_RATIO * frame_w, _PIXEL_DOMAIN_HI_RATIO * frame_w),
        (_PIXEL_DOMAIN_LO_RATIO * frame_h, _PIXEL_DOMAIN_HI_RATIO * frame_h),
    )

def validate_affine(a11: float, a12: float, tx: float,
                    a21: float, a22: float, ty: float) -> Optional[str]:
    """校验一组仿射参数；合法返回 None，不合法返回一句中文原因。

    🔴 为什么必须有这个（2026-09-18 实机前发现）：
    ``calibration_config.ini`` 出厂带的是**占位值 a11..ty 全 0.0**。
    旧代码只要 ``[CameraCalibration]`` 节存在就置 ``is_calibrated = True``，
    于是 6 个参数全 0 也被当成"已标定"，``pixel_to_device()`` 不再返回 None，
    而是把**每一个物体**都算成 (0, 0) —— 全部去装置正中抓。
    这比"未标定"危险得多：未标定是 fail-closed（拒识全部），
    假标定是 fail-open（静默地全抓错）。
    """

    values = (a11, a12, tx, a21, a22, ty)
    if any(not math.isfinite(v) for v in values):
        return "参数含 NaN/Inf"

    if all(abs(v) < 1e-12 for v in values):
        return ("6 个参数全是 0.0 —— 这是配置文件里的占位值，还没做标定。"
                "全 0 会把每个物体都算成装置原点 (0,0)，全部去正中抓")

    det = a11 * a22 - a12 * a21
    scale_x = math.hypot(a11, a12)
    scale_y = math.hypot(a21, a22)
    # 用【相对】判据：行列式的合理下限与两个尺度之积同阶。
    # 纯绝对阈值有两个毛病：会误杀"数值大但形状良态"的合法标定，
    # 又会放过 `a11=1,a12=1,a21=1,a22=1.000000000001` 这种
    # "看着全是正常数、其实把平面压成一条线"的退化矩阵。
    if abs(det) < 1e-9 * scale_x * scale_y:
        return (f"2x2 子阵接近奇异（det={det:.3e}，尺度积="
                f"{scale_x * scale_y:.3e}）：像素平面几乎被压成一条线，"
                "解不出唯一位置")

    # 量级检查：a11/a12 是"每像素多少毫米"。320 像素要看住约 200mm 的台面，
    # 大致在 0.1~10 mm/px。给一个宽松但能拦住明显垃圾的区间。
    for name, scale in (("X", scale_x), ("Y", scale_y)):
        if not (0.02 <= scale <= 20.0):
            return (f"{name} 方向每像素 {scale:.4f} mm，超出合理范围 0.02~20 —— "
                    "量级不对，多半是参数填错或单位混了")

    # 平移量检查：仿射的输出就是台面毫米，量级和台面同阶。
    # `ty = 1e9` 这种"读得出来但显然荒谬"的值必须拦住。
    for name, value in (("tx", tx), ("ty", ty)):
        if abs(value) > 1.0e4:
            return (f"{name}={value:g} 超出合理量级（|{name}| > 1e4 mm）—— "
                    "多半是参数填错，或 mm 与 0.1mm 混了")

    return None


# ITEM_TASK 的 X/Y 是协议可序列化的 ±145.0mm（interface-contract §5.2，
# 镜像固件 EC_MOTION_WORKSPACE_LIMIT_MM10 = 1450）。
# 工作区限制必须落在它里面：否则本模块会"放行"一个直到 encode 才炸的坐标，
# 那件会在发帧那一刻把整条链带走，而不是安静地被拒识。
_SERIALIZABLE_LIMIT_MM = 145.0


def validate_workspace(x_limits: Tuple[float, float],
                       y_limits: Tuple[float, float]) -> Optional[str]:
    """校验工作区限制；合法返回 None，否则返回一句中文原因。

    三条：有限；min <= max；落在 ±145.0mm 内。
    """

    for name, limits in (("X", x_limits), ("Y", y_limits)):
        lo, hi = limits
        if not (math.isfinite(lo) and math.isfinite(hi)):
            return f"{name} 限制含 inf/NaN（{lo}, {hi}）"
        if lo > hi:
            return f"{name} 的 min={lo} 大于 max={hi}"
        if lo < -_SERIALIZABLE_LIMIT_MM or hi > _SERIALIZABLE_LIMIT_MM:
            return (f"{name} 限制 [{lo}, {hi}] 超出协议可序列化范围 "
                    f"±{_SERIALIZABLE_LIMIT_MM}mm —— 越界坐标会在 "
                    "encode_item_task_payload 那一刻才抛，会把那件乃至整条链带走")
    return None

class PixelToDeviceConverter:
    """像素→装置坐标转换器（仿射变换 + 高度视差补偿）"""

    def __init__(self, config_path: str | Path | None = None):
        """
        Args:
            config_path: 标定配置文件路径，默认 电控/calibration_config.ini
                        若文件不存在，进入未标定状态（所有转换返回 None）
        """
        if config_path is None:
            # 默认路径：本文件在 电控/src/electrical_control/rpi/ 下，
            # parent×4 = rpi → electrical_control → src → 电控，
            # 标定文件就在 电控/ 那一层。
            # 🔴 2026-09-18 修正：旧写法是 parent×4 之后再拼一个 "电控"，
            #    实际解析成 电控/电控/calibration_config.ini（多了一层），
            #    该文件永远不存在 → 静默进入"未标定" → 一件都出不了货。
            config_path = (Path(__file__).resolve().parent.parent.parent.parent
                           / "calibration_config.ini")

        self.config_path = Path(config_path)
        self.affine_matrix: np.ndarray | None = None  # 3x3 仿射变换矩阵
        self.camera_height = 400.0  # 默认 400mm
        self.object_heights: dict[int, float] = {}  # {box_id: height_mm}
        self.x_limits = (-82.5, 82.5)  # mm
        self.y_limits = (-82.5, 82.5)  # mm
        # 工具链几何偏移不属于相机标定。旧配置没有 [ToolOffset] 时保持 0，
        # 由 make_grasp_point_for_target 在 pixel_to_device() 结果之后应用。
        self.tool_offset_mm = (0.0, 0.0)
        self.last_rejection_reason: str | None = None
        # 视觉链路输出的帧尺寸，只用于求"图像中心"（见 _optical_axis_point）。
        self.frame_width = 320.0
        self.frame_height = 320.0
        # 有效像素区间随帧尺寸换算（见 pixel_domain_limits）：
        # 未标定时按 320×320 的旧口径，加载配置后按实际 frame_width/height 重算。
        self.pixel_limits = pixel_domain_limits(320.0, 320.0)
        self.is_calibrated = False

        if self.config_path.exists():
            try:
                self._load_calibration()
            except Exception as e:
                _LOGGER.error(
                    "标定配置加载失败: %s (文件 %s)，进入未标定状态",
                    e, self.config_path
                )
                self.is_calibrated = False
        else:
            _LOGGER.warning(
                "标定配置文件不存在: %s，进入未标定状态（所有转换返回 None）",
                self.config_path
            )

    def _load_calibration(self) -> None:
        """从配置文件加载标定参数（内部方法，构造时调用）"""
        # 🔴 必须允许行内注释：calibration_config.ini 的 [ObjectHeights] 每行都写成
        #    `1 = 40.0  # 青色 cyan 正方体`。configparser 默认不剥行内注释，
        #    float("40.0  # 青色 ...") 会抛 ValueError → 每一项都被静默跳过
        #    → object_heights 全空 → 每个件都查不到高度。
        config = configparser.ConfigParser(inline_comment_prefixes=("#",))
        config.read(self.config_path, encoding='utf-8')

        if 'CameraCalibration' not in config:
            raise ValueError(f"缺少 [CameraCalibration] 节: {self.config_path}")

        cal = config['CameraCalibration']

        # 读取仿射矩阵（6 参数 → 3x3 矩阵）
        # x = a11*u + a12*v + tx
        # y = a21*u + a22*v + ty
        affine = (cal.getfloat('a11'), cal.getfloat('a12'), cal.getfloat('tx'),
                  cal.getfloat('a21'), cal.getfloat('a22'), cal.getfloat('ty'))
        # 🔴 必须先校验再落盘：占位值全 0 也"能读出来"，但用它换算会把
        #    每个物体都算成 (0,0)。见 validate_affine 的说明。
        problem = validate_affine(*affine)
        if problem is not None:
            raise ValueError(f"仿射参数不合法：{problem}")

        self.affine_matrix = np.array([
            [affine[0], affine[1], affine[2]],
            [affine[3], affine[4], affine[5]],
            [0.0, 0.0, 1.0]
        ], dtype=np.float64)

        self.camera_height = cal.getfloat('camera_height')
        if not (self.camera_height > 0.0 and math.isfinite(self.camera_height)):
            raise ValueError(f"camera_height={self.camera_height} 不是正数")

        # 帧尺寸只用于定位"图像中心"（光轴落点）。MaixCAM 当前是 320x320。
        self.frame_width = cal.getfloat('frame_width', fallback=320.0)
        self.frame_height = cal.getfloat('frame_height', fallback=320.0)
        if not (math.isfinite(self.frame_width) and self.frame_width > 0.0
                and math.isfinite(self.frame_height) and self.frame_height > 0.0):
            raise ValueError(
                f"frame_width/height={self.frame_width}/{self.frame_height} "
                "必须是有限正数（inf/NaN 会让光轴落点算不出来）"
            )
        # 有效像素区间按**实际帧尺寸**换算（2026-10-29 分辨率迁移）
        self.pixel_limits = pixel_domain_limits(self.frame_width, self.frame_height)

        # 读取物体高度（可选节）
        if 'ObjectHeights' in config:
            for box_id_str, height_str in config['ObjectHeights'].items():
                try:
                    box_id = int(box_id_str)
                    height = float(height_str)
                    self.object_heights[box_id] = height
                except ValueError:
                    _LOGGER.warning(
                        "跳过无效物体高度配置: %s = %s",
                        box_id_str, height_str
                    )

        # 读取工作区限制（可选节）
        if 'WorkspaceLimits' in config:
            lim = config['WorkspaceLimits']
            self.x_limits = (lim.getfloat('x_min'), lim.getfloat('x_max'))
            self.y_limits = (lim.getfloat('y_min'), lim.getfloat('y_max'))
            problem = validate_workspace(self.x_limits, self.y_limits)
            if problem is not None:
                raise ValueError(f"工作区限制不合法：{problem}")

        # 可选节，向后兼容：旧配置缺节/缺键时均为 0.0。
        if 'ToolOffset' in config:
            tool = config['ToolOffset']
            self.tool_offset_mm = (
                tool.getfloat('x_mm', fallback=0.0),
                tool.getfloat('y_mm', fallback=0.0),
            )
            if any(not math.isfinite(value) for value in self.tool_offset_mm):
                raise ValueError(f"工具偏移含 inf/NaN：{self.tool_offset_mm}")

        self.is_calibrated = True
        _LOGGER.info(
            "标定配置已加载: camera_height=%.1fmm, 物体高度 %d 类, "
            "工作区 [%.1f,%.1f]×[%.1f,%.1f]mm, 工具偏移=(%.1f,%.1f)mm",
            self.camera_height,
            len(self.object_heights),
            self.x_limits[0], self.x_limits[1],
            self.y_limits[0], self.y_limits[1],
            self.tool_offset_mm[0], self.tool_offset_mm[1],
        )

    def _optical_axis_point(self) -> Tuple[float, float]:
        """光轴落点（nadir）在**装置坐标**里的位置 = 图像中心经仿射变换后的像。

        🔴 为什么必须有这个（2026-09-18 实机前发现）：
        「高度视差」是物体越高、成像越向**远离光轴**的方向扩张 ——
        张开中心是**光轴落点**，不是装置原点。
        旧写法 ``x_bottom = x_top * scale`` 是"以装置原点为中心缩放"，
        只有当相机恰好装在装置正上方（光轴落点 = 原点）时才等价。

        本项目相机**明确不在正中间**（用户 2026-09-18 确认），所以旧写法会引入
        固定偏差 ``nadir_x * (1 - scale)``：
            nadir 偏 30mm、三棱柱 h=35mm(d=262mm, scale≈1.154) → 偏差 −4.6mm
            nadir 偏 50mm                                          → 偏差 −7.7mm
        而抓取误差预算只有 5mm。

        假设：主点 ≈ 图像中心。若日后发现主点明显偏移，把
        ``frame_width/frame_height`` 换成能表达主点位置的口径，或在配置里
        另行给出 —— 不要在这里悄悄塞一个常数。
        """

        cx = self.frame_width / 2.0
        cy = self.frame_height / 2.0
        matrix = self.affine_matrix
        return (float(matrix[0][0] * cx + matrix[0][1] * cy + matrix[0][2]),
                float(matrix[1][0] * cx + matrix[1][1] * cy + matrix[1][2]))

    def pixel_to_device(
        self,
        u: float,
        v: float,
        class_id: int,
        *,
        check_workspace: bool = True,
    ) -> Optional[Tuple[int, int]]:
        """像素坐标 → 装置坐标（带视差补偿）

        Args:
            u, v: 像素坐标（bbox 中心）
            class_id: 历史参数名，保留关键字兼容；实际传 [ObjectHeights] 的
                      box_id（颜色折叠后的货格号），不是 VisionTarget.class_id。
            check_workspace: 直接调用时保持 True；运动链会先取基准坐标、叠加
                             [ToolOffset]，再检查最终 PICK，因此传 False。

        Returns:
            (x_mm10, y_mm10): 相机换算出的装置基准坐标，单位 0.1mm；
                               尚未叠加 [ToolOffset]
            None: 未标定 / 超出工作区 / 像素或高度非法 / 高度缺失

        ⚠️ 超出工作区的物体应被拒识（记日志，不发 ITEM_TASK）
        """
        self.last_rejection_reason = None
        if not self.is_calibrated:
            self.last_rejection_reason = "未标定"
            return None

        # Step 0: 输入校验 —— 非法像素一律返回 None，不抛异常。
        # 视觉侧给来的 (u,v) 直接来自 wire，宁可拒识这一件，也不能让
        # 一个 NaN/字符串炸在换算里（那会把整条链带走）。
        for name, value in (("u", u), ("v", v)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                self.last_rejection_reason = f"像素非法：{name}={value!r} 不是数字"
                _LOGGER.warning("像素 %s=%r 不是数字：拒识该件", name, value)
                return None
            if not math.isfinite(float(value)):
                self.last_rejection_reason = f"像素非法：{name}={value!r} 不是有限数"
                _LOGGER.warning("像素 %s=%r 不是有限数：拒识该件", name, value)
                return None

        # 有效像素区间：按帧尺寸换算（320×320 时 = (15,305)，与旧行为一致；
        # 1280×720 时 = (60,1220)×(33.75,686.25)，见 pixel_domain_limits）
        x_lo, x_hi = self.pixel_limits[0]
        y_lo, y_hi = self.pixel_limits[1]
        if not (x_lo <= float(u) <= x_hi and y_lo <= float(v) <= y_hi):
            self.last_rejection_reason = (
                "像素域外：pixel=(%g,%g) 不在标定区间 [%g,%g]x[%g,%g]"
                " (frame=%.0fx%.0f)"
                % (float(u), float(v), x_lo, x_hi, y_lo, y_hi,
                   self.frame_width, self.frame_height)
            )
            _LOGGER.warning("%s，拒识该件", self.last_rejection_reason)
            return None

        # 物体高度必须**在配置里明确给出**。
        # 🔴 2026-09-18 收紧：以前查不到就按 h=0（无视差补偿）静默继续 ——
        #    那等于"配置漏了一类，就悄悄少算一截视差"，误差直接进抓取点。
        #    现在查不到 → 拒识该件（fail-closed），并说清是哪个 id。
        try:
            h = self.object_heights[class_id]
        except KeyError:
            self.last_rejection_reason = (
                f"件高表缺项：box_id={class_id!r} 不在 [ObjectHeights]"
            )
            _LOGGER.warning(
                "object_id=%r 不在 [ObjectHeights]（已配置 %s）：拒识该件。"
                "不要用 h=0 顶替 —— 那会静默少算视差",
                class_id, sorted(self.object_heights),
            )
            return None
        if not (math.isfinite(h) and 0.0 <= h < self.camera_height):
            self.last_rejection_reason = (
                f"件高非法：box_id={class_id!r}, h={h!r}, "
                f"camera_height={self.camera_height:.1f}"
            )
            _LOGGER.error(
                "object_id=%r 的高度 h=%r 非法（要求 0 <= h < camera_height=%.1f）："
                "拒识该件，绝不当成 h=0 静默继续",
                class_id, h, self.camera_height,
            )
            return None

        # Step 1: 仿射变换（像素 → 顶面装置坐标 mm）
        pixel_vec = np.array([float(u), float(v), 1.0], dtype=np.float64)
        device_vec = self.affine_matrix @ pixel_vec
        x_top, y_top = float(device_vec[0]), float(device_vec[1])

        # Step 2: 高度视差补偿 —— 以【镜头光轴落点】为基准，不是装置原点
        if h > 0.0:
            # 🔴 2026-09-18 修正：这里必须是【除】，不是乘。
            #   相机在高度 H、光轴落 N。物体底面 B、高 h，其【顶面】在画面里
            #   看起来"跑"到了更远的地面位置
            #       G = N + (B - N) × H/(H-h)          （scale = H/(H-h) > 1）
            #   仿射是在【台面】上标定的，所以 affine(像素) 给的是 G（表观位置），
            #   不是 B。要还原真实底面：
            #       B = N + (G - N) × (H-h)/H = N + (G - N) ÷ scale
            #   具体算例（H=262, h=40, scale=1.1802, 光轴在原点, B=(0,50)）：
            #       射线落到地面 = 50×1.1802 = 59.0 = G
            #       59.0 ÷ 1.1802 = 50.0 = B  ✓
            #       59.0 × 1.1802 = 69.6      ✗（旧实现，误差还翻倍）
            #   光轴上的点 G=N 两种写法都得 N，所以「保持光轴不变」用旧写法也能过 ——
            #   这正是这个 bug 一直没被发现的原因。
            scale = self.camera_height / (self.camera_height - h)
            nadir_x, nadir_y = self._optical_axis_point()
            x_bottom = nadir_x + (x_top - nadir_x) / scale
            y_bottom = nadir_y + (y_top - nadir_y) / scale
        else:
            x_bottom, y_bottom = x_top, y_top

        # Step 3: 边界检查（用**补偿后**的坐标，不是补偿前的）
        if check_workspace and not (self.x_limits[0] <= x_bottom <= self.x_limits[1]):
            self.last_rejection_reason = (
                f"越界：换算坐标 x={x_bottom:.3f}mm 不在 "
                f"[{self.x_limits[0]:.1f},{self.x_limits[1]:.1f}]mm"
            )
            _LOGGER.warning("%s，拒识该件", self.last_rejection_reason)
            return None
        if check_workspace and not (self.y_limits[0] <= y_bottom <= self.y_limits[1]):
            self.last_rejection_reason = (
                f"越界：换算坐标 y={y_bottom:.3f}mm 不在 "
                f"[{self.y_limits[0]:.1f},{self.y_limits[1]:.1f}]mm"
            )
            _LOGGER.warning("%s，拒识该件", self.last_rejection_reason)
            return None

        # Step 4: 转换为 0.1mm 单位（协议单位）
        x_mm10 = int(round(x_bottom * 10))
        y_mm10 = int(round(y_bottom * 10))

        return (x_mm10, y_mm10)

# 拒识日志限频间隔：同一原因首次必打，之后每 _REJECT_LOG_EVERY 次打一条（带累计次数）。
# 2026-09-22 实测：一个落在"相机看得见、夹爪够不到"死带里的件，被逐帧拒识 3834 次，
# 11 分 34 秒里日志从第 118 行涨到第 4020 行、文件 899 KB，真问题全被淹掉。
_REJECT_LOG_EVERY = 100


def make_grasp_point_for_target(converter: PixelToDeviceConverter) -> GraspPointForTarget:
    """造出 ``build_item_task_queue`` 要的 ``grasp_point_for_target``。

    入参是 ``VisionTarget``，出参是 ``(x_mm10, y_mm10)`` 或 ``None``。

    ⚠️ 用 ``box_id`` 查物体高度，**不是** ``class_id``：
    ``[ObjectHeights]`` 的键是 box_id（见 ``calibration_config.ini`` 的注释）。
    ``VisionTarget.class_id`` 的形状语义与 ``box_id`` 不等价。
    当前校赛解析器把同一 id 字节同时写进两字段，但既有逻辑测试允许两者不同；
    高度查询只能依照明确的 box_id，不能依赖 wire 解析产生的数值相等。

    未标定 / 越界 / box_id 缺失 一律返回 ``None``，该件被 ``build_item_task_queue``
    丢件（拒识），**绝不**退回 (0,0) —— 那就是"所有件都去正中抓"，等于没有视觉。
    """

    class _Lookup:
        def __init__(self) -> None:
            self._last_target: VisionTarget | None = None
            self._last_reason = "未知原因"
            # 2026-09-22 拒识日志限频。实测一轮里【同一个件】被逐帧拒识 3834 次，
            # 每条一模一样的 WARNING 把日志灌到 899 KB，真问题全被淹掉
            # （/home/pi/logs/round-R8-183157.log：11 分 34 秒里只有同一条
            #   "PICK=(-28.2,-106.9) 不在工作区"）。
            # 只在【同一原因】首次 + 每 _REJECT_LOG_EVERY 次打一条，并带累计次数。
            # 不必在成功时重置：reason 里含坐标，换了件就是换了 key。
            self._reject_key = ""
            self._reject_n = 0

        def __call__(self, target: VisionTarget) -> Optional[Tuple[int, int]]:
            self._last_target = target
            if not converter.is_calibrated:
                self._last_reason = "未标定"
                return None
            box_id = target.box_id
            if box_id is None:
                self._last_reason = "件高表缺项：目标没有 box_id"
                return None

            # T1：pixel_to_device 只负责相机像素→装置基准坐标；工具几何偏移在
            # 运动链适配器里、拿到该结果以后再叠加。相机移动只需重标相机参数。
            base = converter.pixel_to_device(
                target.pixel_x, target.pixel_y, box_id, check_workspace=False
            )
            if base is None:
                self._last_reason = converter.last_rejection_reason or "未知原因"
                return None

            offset_x_mm10 = int(round(converter.tool_offset_mm[0] * 10.0))
            offset_y_mm10 = int(round(converter.tool_offset_mm[1] * 10.0))
            result = (base[0] + offset_x_mm10, base[1] + offset_y_mm10)

            # 运动链刻意跳过基准坐标边界；只校验叠加偏移后最终会下发的 PICK。
            x_mm, y_mm = result[0] / 10.0, result[1] / 10.0
            if not (converter.x_limits[0] <= x_mm <= converter.x_limits[1]
                    and converter.y_limits[0] <= y_mm <= converter.y_limits[1]):
                self._last_reason = (
                    "越界：pixel_to_device=%s 加 ToolOffset=(%.1f,%.1f)mm 后 "
                    "PICK=(%.1f,%.1f)mm，不在工作区 [%.1f,%.1f]x[%.1f,%.1f]mm"
                    % (
                        base,
                        converter.tool_offset_mm[0], converter.tool_offset_mm[1],
                        x_mm, y_mm,
                        converter.x_limits[0], converter.x_limits[1],
                        converter.y_limits[0], converter.y_limits[1],
                    )
                )
                if self._last_reason == self._reject_key:
                    self._reject_n += 1
                else:
                    self._reject_key = self._last_reason
                    self._reject_n = 1
                if (self._reject_n == 1) or (self._reject_n % _REJECT_LOG_EVERY == 0):
                    _LOGGER.warning(
                        "%s，拒识该件（同一原因已累计 %d 次）",
                        self._last_reason,
                        self._reject_n,
                    )
                return None

            self._last_reason = ""
            return result

        def rejection_reason_for_target(self, target: VisionTarget) -> str:
            if target is not self._last_target:
                return "未知原因（拒识原因与目标未配对）"
            return self._last_reason or "未知原因"

    return _Lookup()

# ========== 主机侧轻量自检（无 pytest，用 assert） ==========

if __name__ == "__main__":
    test_config = Path(__file__).with_name(f".pixel_to_device_selftest_{os.getpid()}.ini")
    try:
        test_config.write_text("""[CameraCalibration]
a11=0.5
a12=0
tx=-80
a21=0
a22=0.5
ty=-80
camera_height=200
frame_width=320
frame_height=320

[ObjectHeights]
1=0
3=40

[WorkspaceLimits]
x_min=-95
x_max=90
y_min=-97.5
y_max=92.5

[ToolOffset]
x_mm=-75
y_mm=-25
""", encoding="utf-8")
        converter = PixelToDeviceConverter(test_config)
        assert converter.is_calibrated
        assert converter.pixel_to_device(160, 160, 1) == (0, 0)
        assert converter.pixel_to_device(180, 180, 1) == (100, 100)
        # 2026-09-22 修：原来用 pixel=(180,141)，而 _CALIBRATED_PIXEL_X/Y_LIMITS=(15.0,305.0)
        # ⇒ 它在区间内、不会被拒 ⇒ 这条断言从写下起就是坏的（自检根本跑不过）。
        # 要测"像素域外"必须给真正域外的 v（10 < 15）。
        assert converter.pixel_to_device(180, 10, 1) is None
        assert "像素域外" in (converter.last_rejection_reason or "")
        assert converter.pixel_to_device(180, 180, 99) is None
        assert "件高表缺项" in (converter.last_rejection_reason or "")
        grasp = make_grasp_point_for_target(converter)
        from types import SimpleNamespace
        target = SimpleNamespace(pixel_x=180, pixel_y=180, box_id=1)
        assert grasp(target) == (-650, -150)

        # ── 拒识日志限频（2026-09-22）────────────────────────────────
        # 要触发 :506 那条【工作区越界】分支（而不是基准系的"像素域外"），
        # 像素必须落在 _CALIBRATED_PIXEL_X/Y_LIMITS=(15,305) 之内。
        # 本测试标定：base=(0.5u-80, 0.5v-80)mm，TO=(-75,-25) ⇒ PICK=(base_x-75, base_y-25)。
        #   u=20 ⇒ base_x=-70 ⇒ PICK_x=-145.0mm < x_min=-95.0 ⇒ 越界 ✅
        #   v=160 ⇒ base_y=0  ⇒ PICK_y=-25.0mm  ⇒ y 正常
        far = SimpleNamespace(pixel_x=20, pixel_y=160, box_id=1)
        assert grasp(far) is None
        assert "不在工作区" in (grasp._reject_key or ""), grasp._reject_key
        assert grasp._reject_n == 1, grasp._reject_n      # 首次：计数=1（会打日志）
        assert grasp(far) is None
        assert grasp._reject_n == 2, grasp._reject_n      # 同因第 2 次：只累加，不再刷屏
        assert grasp(far) is None
        assert grasp._reject_n == 3, grasp._reject_n
        # 换了件（reason 含坐标）⇒ 计数器重新从 1 开始
        other = SimpleNamespace(pixel_x=25, pixel_y=160, box_id=1)
        assert grasp(other) is None
        assert grasp._reject_n == 1, grasp._reject_n

        print("[PASS] pixel_to_device 轻量主机自检通过")
    finally:
        test_config.unlink(missing_ok=True)
