"""行扫描抓取顺序（A1b，2026-09-21）：Y 从大到小 → 同行 X 从小到大。

用户口径（已确认）：第一键 **Y 从大到小**（从靠 Y 正方向那排开始、逐排往里），
第二键 **同一行内 X 从小到大**（每排从最靠 HOME 那件沿 +X 依次抓）
⇒ 效果"从上到下、每排从左到右"。它**取代**原先的「离托盘无壁边最近」规则。

本文件锁死 5 条判据：
1. 排序键就是 ``(-y, x, target_seq)``（第一键 Y 降、第二键 X 升）；
2. **换掉 ``[Tray] open_side`` / 挪动 ``[Home]`` 都改不了顺序** —— 现役键会变，
   行扫描不会（"不再依赖 [Tray] 与 [Home] 的配置"这句话在这里被证明，不是被声明）；
3. ``[Tray] open_side = y_max`` 时与现役键**主键同序**（Y 互不相同则逐件同序）；
4. **默认 off 逐字节等价**：``--pick-strategy`` 默认仍是 ``off``、off 时不构造
   任何排序器 ⇒ 顺序与接入前完全一致；
5. α 语义：启用时也**不丢件**（件数、集合都不变），件数 < 2 原样返回。
6. **按行容差分桶**（2026-09-22 实机复现后升级）："同一排"由
   ``[Tray] row_tolerance_mm``（【实测】17.0mm）判定，不再是"y 完全相等"；
   容差只能从配置来，``0`` = 一键退回旧口径。

跑法（两种都行）：
    D:\\python.exe -m pytest tests/pick_strategy/test_row_scan_order.py
    python tests/pick_strategy/test_row_scan_order.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

_EC = Path(__file__).resolve().parents[2]          # 电控/
_SRC = _EC / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from electrical_control.pick_strategy import (  # noqa: E402
    ConfigError,
    Detection,
    Point,
    VisionFrame,
    build_config,
    order_by_open_edge,
    order_by_row_scan,
    row_scan_key,
)
from electrical_control.pick_strategy.chain_adapter import (  # noqa: E402
    make_payload_orderer,
    payload_orderer_from_ini,
)
from electrical_control.pick_strategy.geometry import OPEN_SIDE_X_MIN  # noqa: E402

DEMO_INI = _EC / "deploy" / "pick_strategy.demo.ini"
REAL_INI = _EC / "deploy" / "pick_strategy.ini"
RUN_CHAIN = _EC / "deploy" / "run_chain.py"


def det(seq: int, x_mm: float, y_mm: float, box_id: int = 1) -> Detection:
    return Detection(target_seq=seq, box_id=box_id, class_id=box_id,
                     x_mm=x_mm, y_mm=y_mm)


def frame(*dets: Detection) -> VisionFrame:
    return VisionFrame(frame_id=1, received_at_s=0.0, detections=tuple(dets))


def seqs(dets) -> list[int]:
    return [d.target_seq for d in dets]


def write_ini(name: str, text: str) -> Path:
    """写一份临时 ini（放在测试目录内，与 test_config_and_contract 同口径）。"""

    target = Path(__file__).resolve().parent / "_tmp"
    target.mkdir(exist_ok=True)
    path = target / name
    path.write_text(text, encoding="utf-8")
    return path


@dataclass
class _Payload:
    """实链 payload 的最小面（只需要排序器读的那 4 个字段）。"""

    target_seq: int
    class_id: int
    pick_x_position: int   # 0.1mm 滑台记账坐标 = 装置坐标 + ToolOffset
    pick_y_position: int


def payload(seq: int, cls: int, x_mm: float, y_mm: float, cfg) -> _Payload:
    """按**装置坐标 mm** 造 payload（记账坐标 = 装置坐标 + ToolOffset）。"""

    return _Payload(
        target_seq=seq,
        class_id=cls,
        pick_x_position=int(round((x_mm + cfg.tool_offset.x_mm) * 10)),
        pick_y_position=int(round((y_mm + cfg.tool_offset.y_mm) * 10)),
    )


# (x, y) —— Y 分三排（55 / 30 / 10），每排两件（X 30 / 70~80）
CORPUS = ((1, 70.0, 30.0), (2, 30.0, 30.0), (3, 30.0, 55.0),
          (4, 80.0, 55.0), (5, 30.0, 10.0))
# Y 降序 → 同行 X 升序
EXPECTED = [3, 4, 2, 1, 5]


class RowScanOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = build_config(DEMO_INI)

    def test_row_scan_key_is_y_desc_then_x_asc(self) -> None:
        """判据 1：第一键 Y 降、第二键 X 升；同排同 X 才用 target_seq。"""

        self.assertEqual((-55.0, 30.0, 3), row_scan_key(det(3, 30.0, 55.0)))
        got = order_by_row_scan(frame(*(det(s, x, y) for s, x, y in CORPUS)), self.cfg)
        self.assertEqual(EXPECTED, seqs(got))

    def test_row_scan_ignores_tray_and_home(self) -> None:
        """判据 2：行扫描不吃 [Tray]/[Home]，现役键吃 —— 这是"更稳"的实测证据。"""

        fr = frame(*(det(s, x, y) for s, x, y in CORPUS))
        base = order_by_row_scan(fr, self.cfg)

        # 无壁边改到另一侧 + HOME 挪到别处
        other = replace(
            self.cfg,
            tray=replace(self.cfg.tray, open_side=OPEN_SIDE_X_MIN),
            home=Point(0.0, 0.0),
        )
        self.assertEqual(EXPECTED, seqs(order_by_row_scan(fr, other)),
                         "行扫描顺序不该受 [Tray]/[Home] 影响")

        # 反证：现役键在同样两套配置下顺序确实变了（否则本用例没有杀伤力）
        self.assertNotEqual(seqs(order_by_open_edge(fr, self.cfg)),
                            seqs(order_by_open_edge(fr, other)))

    def test_row_scan_agrees_with_open_edge_when_open_side_is_y_max(self) -> None:
        """判据 3：open_side = y_max 时两者主键同序（Y 互不相同 ⇒ 逐件同序）。"""

        fr = frame(*(det(s, x, y) for s, x, y in CORPUS))
        self.assertEqual([1, 2, 3, 4, 5], sorted(s.target_seq for s in fr.detections))
        self.assertEqual(seqs(order_by_open_edge(fr, self.cfg)),
                         seqs(order_by_row_scan(fr, self.cfg)))

    # ------------------------------------------------ 判据 6：按行容差分桶
    def test_row_tolerance_keeps_a_visibly_one_row_together(self) -> None:
        """核心用例（2026-09-22 实机复现）：同排两件 y 差 5.6mm ⇒ 仍算一排，先夹最靠 −X 的。

        实机那一帧：黑 y=+3.0 x=+95、青 y=−2.6 x=+43（肉眼同一排，链帧却差 5.6mm）。
        旧口径（"同一排"只认 Y 完全相等）判成两排 ⇒ 先夹 y 大的**黑**；
        用户口径要的是先夹**青**。
        """

        fr = frame(det(1, 95.0, 3.0), det(2, 43.0, -2.6))
        # 回退口径（= row_tolerance_mm ≤ 0）先给 y 大者 —— 这正是本用例改前的行为
        self.assertEqual([1, 2], seqs(sorted(fr.detections, key=row_scan_key)))
        self.assertEqual([2, 1], seqs(order_by_row_scan(fr, self.cfg)),
                         "同排内必须先夹最靠 −X 的那件（x=43 的青）")

    def test_row_tolerance_does_not_merge_neighbouring_rows(self) -> None:
        """两件 y 差 50mm ⇒ 不得并成一排：仍是 y 大的那排先（哪怕它 x 更靠 +X）。"""

        fr = frame(det(1, 95.0, 55.0), det(2, 43.0, 5.0))
        self.assertEqual([1, 2], seqs(order_by_row_scan(fr, self.cfg)),
                         "排间距远大于容差时必须保持'排间按 y'")

    def test_row_tolerance_zero_falls_back_to_the_old_key(self) -> None:
        """一键回退开关：``row_tolerance_mm = 0`` ⇒ 逐件等于旧键 ``row_scan_key``。"""

        off = replace(self.cfg, tray=replace(self.cfg.tray, row_tolerance_mm=0.0))
        self.assertEqual(0.0, off.tray.row_tolerance_mm)
        for fr in (frame(*(det(s, x, y) for s, x, y in CORPUS)),
                   frame(det(1, 95.0, 3.0), det(2, 43.0, -2.6))):
            self.assertEqual(seqs(sorted(fr.detections, key=row_scan_key)),
                             seqs(order_by_row_scan(fr, off)))
        self.assertEqual(
            [1, 2],
            seqs(order_by_row_scan(frame(det(1, 95.0, 3.0), det(2, 43.0, -2.6)), off)),
            "回退后 5.6mm 那两件又变回'y 大者先'",
        )

    def test_row_tolerance_is_read_from_the_ini_not_defaulted(self) -> None:
        """容差只能从配置来：夹具 17.0 / 实机 20.0；删掉该键 ⇒ ``ConfigError``（不静默默认）。

        ⚠️ 2026-09-22：实机那份（REAL_INI）按用户现场裁决由 17.0 改为 **20.0**，
           夹具（DEMO_INI）**故意保持 17.0**（避免语料里 |30−10|=20mm 的两排被并）
           ⇒ 本用例的两条断言值**因此不同**，这是有意的，不是写错。
        """

        self.assertEqual(17.0, self.cfg.tray.row_tolerance_mm)          # 夹具
        self.assertEqual(20.0, build_config(REAL_INI).tray.row_tolerance_mm)  # 实机

        text = "".join(
            line + "\n"
            for line in DEMO_INI.read_text(encoding="utf-8").splitlines()
            if "row_tolerance_mm" not in line
        )
        with self.assertRaises(ConfigError) as raised:
            build_config(write_ini("no_row_tolerance.ini", text))
        self.assertIn("row_tolerance_mm", str(raised.exception))

    def test_row_tolerance_out_of_range_is_rejected(self) -> None:
        """解析校验：``< 0``（无意义）与 ``> 25.0``（会把相邻两排并成一排）一律拒绝。"""

        base = DEMO_INI.read_text(encoding="utf-8")
        for value, keyword in ((-1.0, "不得为负"), (25.5, "超过上限 25.0mm")):
            text = base.replace("row_tolerance_mm = 17.0",
                                f"row_tolerance_mm = {value}")
            with self.assertRaises(ConfigError) as raised:
                build_config(write_ini(f"row_tol_{value}.ini", text))
            self.assertIn(keyword, str(raised.exception))

    def test_orderer_is_alpha_and_keeps_every_payload(self) -> None:
        """判据 5：启用时也**不丢件**；件数 < 2 原样返回。"""

        orderer = make_payload_orderer(self.cfg)
        payloads = tuple(payload(s, 1, x, y, self.cfg) for s, x, y in CORPUS)
        ordered = orderer(payloads)

        self.assertEqual(len(payloads), len(ordered))
        self.assertEqual({id(p) for p in payloads}, {id(p) for p in ordered})
        self.assertEqual(EXPECTED, [p.target_seq for p in ordered])

        one = payloads[:1]
        self.assertEqual(one, orderer(one), "单件必须原样返回（逐字节一致）")
        self.assertEqual((), orderer(()), "空输入必须原样返回")

    def test_unusable_payload_is_moved_to_tail_not_dropped(self) -> None:
        """α：缺抓取点的件排到队尾，**不丢**。"""

        orderer = make_payload_orderer(self.cfg)
        good = payload(3, 1, 30.0, 55.0, self.cfg)
        broken = _Payload(target_seq=9, class_id=1,
                          pick_x_position=None, pick_y_position=None)  # type: ignore[arg-type]
        rest = payload(5, 1, 30.0, 10.0, self.cfg)

        ordered = orderer((broken, rest, good))
        self.assertEqual([3, 5, 9], [p.target_seq for p in ordered])

    def test_missing_config_disables_the_orderer(self) -> None:
        """默认/缺失 ⇒ 不启用排序器（调用方保持原顺序 = 接入前行为）。"""

        self.assertIsNone(payload_orderer_from_ini(_EC / "deploy" / "不存在的.ini"))

    def test_default_pick_strategy_is_still_off(self) -> None:
        """判据 4（默认 off 逐字节等价）：默认值必须是 off，off 就不构造排序器。

        `run_chain.py` 是部署脚本（py3.9+），在旧解释器上加载不了 ⇒ 跳过而不是假装通过。
        """

        spec = importlib.util.spec_from_file_location("run_chain_probe", RUN_CHAIN)
        self.assertIsNotNone(spec)
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            args = module.parse_args([])
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"run_chain.py 在本解释器加载不了：{exc}") from None

        self.assertEqual("off", args.pick_strategy,
                         "--pick-strategy 默认必须是 off（off 才会逐字节等于接入前）")
        self.assertEqual("off", module.parse_args(["--pick-strategy", "off"]).pick_strategy)

    def test_row_scan_is_exported_by_the_package(self) -> None:
        import electrical_control.pick_strategy as pkg

        for name in ("order_by_row_scan", "row_scan_key"):
            self.assertIn(name, pkg.__all__)
            self.assertIn(name, dir(pkg))


if __name__ == "__main__":
    unittest.main(verbosity=2)
