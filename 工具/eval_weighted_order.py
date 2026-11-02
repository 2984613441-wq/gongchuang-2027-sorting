# -*- coding: utf-8 -*-
"""加权排序可行性测评（离线仿真，不碰硬件、不发串口）。

目的（用户 2026-11-02）：在把 `order_mode=weighted` 用于实机**之前**，先量化评估：
  1. 顺序是否稳定（权重 ±10% 扰动 / 传感器噪声下，首位与整体顺序会变吗）
  2. 与「先易后难」是否冲突（前端口径会不会把难件抢到前面）
  3. 行程代价（按新顺序执行，总行程 vs 就近贪心 vs 行扫描）
  4. 对 `[Tray] open_side` 误配的敏感性（装错就全乱 ⇒ 必须先实测）

用法：
    cd 电控 && $env:PYTHONPATH="$PWD\\src"
    python ..\工具\eval_weighted_order.py [--out 报告.json] [--trials 300]
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sys
from pathlib import Path

_EC = Path(__file__).resolve().parents[1] / "电控"
sys.path.insert(0, str(_EC / "src"))

from electrical_control.pick_strategy.config import build_config          # noqa: E402
from electrical_control.pick_strategy.geometry import Point              # noqa: E402
from electrical_control.pick_strategy.orderer import (                   # noqa: E402
    DEFAULT_WEIGHTS,
    order_by_weighted,
    score_detections,
)
from electrical_control.pick_strategy.selector import (                  # noqa: E402
    Detection,
    VisionFrame,
    order_by_group_scan,
    order_by_row_scan,
)

INI = _EC / "deploy" / "pick_strategy.demo.ini"
# 形状号 → 难度层（与 selector.PICK_TIER_BY_CLASS_ID 一致）
TIER = {1: 0, 2: 0, 3: 1, 4: 0, 5: 2, 6: 0}
SHAPES = (1, 2, 3, 4, 5, 6)


def make_frame(rng: random.Random, n: int, cfg) -> VisionFrame:
    """在托盘工作域内随机撒 n 件（避免重叠），class_id 按 box_id 模式=形状号。"""
    xs = (-80.0, 80.0)
    ys = (-85.0, 80.0)
    pts: list[tuple[float, float]] = []
    dets = []
    for i in range(n):
        for _ in range(50):
            x = rng.uniform(*xs)
            y = rng.uniform(*ys)
            if all(math.hypot(x - px, y - py) > 34.0 for px, py in pts):
                break
        else:
            continue
        pts.append((x, y))
        shape = rng.choice(SHAPES)
        dets.append(Detection(target_seq=i + 1, box_id=shape, class_id=shape,
                              x_mm=x, y_mm=y, confidence=rng.randint(70, 96)))
    return VisionFrame(frame_id=1, received_at_s=0.0, detections=tuple(dets))


def total_travel(order, home: Point, drop: Point) -> float:
    """按给定顺序执行的总行程（home→pick1→drop→pick2→…→drop）。"""
    pos = home
    dist = 0.0
    for det in order:
        dist += math.hypot(det.x_mm - pos.x_mm, det.y_mm - pos.y_mm)
        dist += math.hypot(drop.x_mm - det.x_mm, drop.y_mm - det.y_mm)
        pos = drop
    return dist


def first_seq(order) -> int:
    return order[0].target_seq if order else -1


def order_agreement(a, b) -> float:
    """两序列的 Kendall tau（-1..1，1=完全同序）。"""
    seq_a = [d.target_seq for d in a]
    seq_b = [d.target_seq for d in b]
    common = [s for s in seq_a if s in seq_b]
    if len(common) < 2:
        return 1.0
    rank_b = {s: i for i, s in enumerate(seq_b)}
    pairs = itertools.combinations(common, 2)
    agree = disc = 0
    pos_a = {s: i for i, s in enumerate(seq_a)}
    for x, y in pairs:
        da = pos_a[x] - pos_a[y]
        db = rank_b[x] - rank_b[y]
        if da * db > 0:
            agree += 1
        elif da * db < 0:
            disc += 1
    tot = agree + disc
    return 1.0 if tot == 0 else (agree - disc) / tot


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=300)
    ap.add_argument("--pieces", type=int, default=6)
    ap.add_argument("--seed", type=int, default=20261102)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    cfg = build_config(INI)
    rng = random.Random(args.seed)
    home, drop = cfg.home, Point(20.0, 60.0)

    base = {"front": cfg.weight_front, "pick": cfg.weight_pick,
            "route": cfg.weight_route, "isolation": cfg.weight_isolation}

    stats = {
        "trials": 0, "pieces_total": 0,
        "first_changed_pct_perturb": 0.0,
        "tau_mean_perturb": 0.0,
        "hard_first_pct": 0.0,          # 首件是难件（圆柱/圆锥）的比例
        "tau_vs_group": 0.0, "tau_vs_row": 0.0,
        "travel_weighted": 0.0, "travel_group": 0.0,
        "travel_row": 0.0, "travel_greedy": 0.0,
        "flip_x_pct": 0.0,              # 相邻两件 X 方向反复横跳的比例
        "open_side_flip_tau": 0.0,      # open_side 误配成 x_max 后与原顺序的一致性
    }
    perturb_cfgs = []
    for key in base:
        for delta in (-0.1, 0.1):
            w = dict(base)
            w[key] = max(0.0, w[key] + delta)
            perturb_cfgs.append(w)

    for _ in range(args.trials):
        fr = make_frame(rng, args.pieces, cfg)
        usable = fr.detections
        if len(usable) < 3:
            continue
        stats["trials"] += 1
        stats["pieces_total"] += len(usable)

        order_w = order_by_weighted(fr, cfg, weights=base)
        order_group = order_by_group_scan(fr, cfg)
        order_row = order_by_row_scan(fr, cfg)
        # 贪心就近（近似现状 greedy_tsp 的第一步）：从 home 起每次取最近
        rest = list(usable)
        pos, greedy = home, []
        while rest:
            nxt = min(rest, key=lambda d: math.hypot(d.x_mm - pos.x_mm,
                                                     d.y_mm - pos.y_mm))
            greedy.append(nxt)
            rest.remove(nxt)
            pos = Point(nxt.x_mm, nxt.y_mm)

        # 1) 权重扰动稳定性
        first_changed = 0
        taus = []
        base_first = first_seq(order_w)
        for w in perturb_cfgs:
            o = order_by_weighted(fr, cfg, weights=w)
            if first_seq(o) != base_first:
                first_changed += 1
            taus.append(order_agreement(order_w, o))
        stats["first_changed_pct_perturb"] += 100.0 * first_changed / len(perturb_cfgs)
        stats["tau_mean_perturb"] += sum(taus) / len(taus)

        # 2) 难件是否被抢到首位
        if order_w:
            tier0 = TIER.get(int(order_w[0].class_id), 0)
            stats["hard_first_pct"] += 100.0 if tier0 >= 1 else 0.0

        # 3) 与其它口径的一致性 / 行程
        stats["tau_vs_group"] += order_agreement(order_w, order_group)
        stats["tau_vs_row"] += order_agreement(order_w, order_row)
        stats["travel_weighted"] += total_travel(order_w, home, drop)
        stats["travel_group"] += total_travel(order_group, home, drop)
        stats["travel_row"] += total_travel(order_row, home, drop)
        stats["travel_greedy"] += total_travel(greedy, home, drop)

        # 4) 横跳：相邻件 X 方向符号反复
        flips = 0
        for a, b in zip(order_w, order_w[1:]):
            if (a.x_mm - home.x_mm) * (b.x_mm - home.x_mm) < 0:
                flips += 1
        stats["flip_x_pct"] += 100.0 * flips / max(1, len(order_w) - 1)

        # 5) open_side 误配敏感性
        try:
            bad = build_config(INI)
            # 直接改 tray 的 open_side 不现实（frozen dataclass），改为把权重里 front 置 0
            o_nofront = order_by_weighted(fr, cfg,
                                          weights={"front": 0.0, "pick": 0.55,
                                                   "route": 0.35, "isolation": 0.10})
            stats["open_side_flip_tau"] += order_agreement(order_w, o_nofront)
        except Exception:
            pass

    if not stats["trials"]:
        print("没有有效帧，检查参数")
        return 1

    t = stats["trials"]
    result = {
        "trials": t,
        "avg_pieces": round(stats["pieces_total"] / t, 2),
        "weights": base,
        "first_changed_pct_under_plus_minus_0.1": round(stats["first_changed_pct_perturb"] / t, 2),
        "kendall_tau_mean_under_perturb": round(stats["tau_mean_perturb"] / t, 4),
        "hard_piece_first_pct": round(stats["hard_first_pct"] / t, 2),
        "kendall_tau_vs_group": round(stats["tau_vs_group"] / t, 4),
        "kendall_tau_vs_row_scan": round(stats["tau_vs_row"] / t, 4),
        "travel_weighted_mm": round(stats["travel_weighted"] / t, 1),
        "travel_group_mm": round(stats["travel_group"] / t, 1),
        "travel_row_scan_mm": round(stats["travel_row"] / t, 1),
        "travel_greedy_mm": round(stats["travel_greedy"] / t, 1),
        "x_zigzag_pct": round(stats["flip_x_pct"] / t, 2),
        "tau_when_front_weight_zero": round(stats["open_side_flip_tau"] / t, 4),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print("\n已写入", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
