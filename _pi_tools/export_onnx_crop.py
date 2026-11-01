#!/usr/bin/env python3
"""把 YOLO11 .pt 导出成「裁剪输出」的 ONNX —— MaixCAM cvimodel 转换的前提。

## 为什么必须裁剪

Ultralytics 导出的 ONNX 输出是一个拼接后的张量（`output0`），
形状 [1, 4+nc, 8400]。而 cvimodel 转换工具要求**分开的两个原始输出节点**：

```
/model.23/dfl/conv/Conv_output_0     ← DFL 的 box 分布，形状 [1, 64, 8, 8] 等
/model.23/Sigmoid_output_0           ← 类别分数，形状 [1, nc, 8, 8] 等
```

所以必须用 `onnx.utils.extract_model` 把这两个**内部节点**提升为图输出。

## 用法

```bash
# 导出（自动找 /model.23/ 下的两个节点）
python _pi_tools/export_onnx_crop.py --pt _runs/yolo11n_6c_448/weights/best.pt --imgsz 448

# 只打印 ONNX 里的候选输出节点（不导出）
python _pi_tools/export_onnx_crop.py --pt xxx.pt --list-only
```

输出：
  `_deploy_maixcam/<name>.onnx`         ← 原始导出（未裁剪，留档）
  `_deploy_maixcam/<name>_export.onnx`  ← 裁剪后（喂给 wsl_convert.sh）
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "_deploy_maixcam"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="导出裁剪输出的 ONNX")
    ap.add_argument("--pt", required=True, help=".pt 权重路径")
    ap.add_argument("--imgsz", type=int, default=448)
    ap.add_argument("--opset", type=int, default=13)
    ap.add_argument("--name", default=None, help="输出名（默认从 pt 目录推断）")
    ap.add_argument("--list-only", action="store_true",
                    help="只打印候选输出节点")
    args = ap.parse_args(argv)

    pt = Path(args.pt)
    if not pt.is_file():
        print("❌ 权重不存在: %s" % pt)
        return 1

    try:
        import onnx
    except Exception as exc:
        print("❌ 需要 onnx: %s" % exc)
        return 1

    # 推断名字：.../yolo11n_6c_448/weights/best.pt → yolo11n_6c_448
    name = args.name or pt.parent.parent.name

    DEPLOY.mkdir(parents=True, exist_ok=True)
    raw_onnx = DEPLOY / ("%s.onnx" % name)
    crop_onnx = DEPLOY / ("%s_export.onnx" % name)

    print("=" * 74)
    print("  YOLO11 → 裁剪输出 ONNX")
    print("=" * 74)
    print("  权重   : %s" % pt)
    print("  名字   : %s" % name)
    print("  imgsz  : %d" % args.imgsz)
    print("  opset  : %d" % args.opset)
    print()

    # ── 1) 导出 ONNX ──────────────────────────────────────────────
    if args.list_only and raw_onnx.is_file():
        print("  [跳过导出，用已有 %s]" % raw_onnx.name)
    else:
        print("  [1/4] ultralytics 导出 ONNX …")
        try:
            from ultralytics import YOLO
        except Exception as exc:
            print("  ❌ 需要 ultralytics: %s" % exc)
            return 1
        model = YOLO(str(pt))
        out = model.export(format="onnx", imgsz=args.imgsz,
                           opset=args.opset, simplify=False, dynamic=False)
        out = Path(str(out))
        if out.resolve() != raw_onnx.resolve():
            shutil.copy2(out, raw_onnx)
        print("  ✅ 原始 ONNX: %s  (%.1f MB)"
              % (raw_onnx.name, raw_onnx.stat().st_size / 1e6))

    # ── 2) 找候选输出节点 ─────────────────────────────────────────
    print()
    print("  [2/4] 扫描候选输出节点 …")
    m = onnx.load(str(raw_onnx))
    graph = m.graph

    # 图的"叶"节点：其输出没被任何其他节点消费
    consumed = set()
    for n in graph.node:
        for i in n.input:
            consumed.add(i)

    leaves = []
    for n in graph.node:
        for o in n.output:
            if o not in consumed:
                leaves.append((n.op_type, o))

    print("    当前图输出（%d 个）:" % len(graph.output))
    for o in graph.output:
        print("      - %s" % o.name)

    print("    真正的叶节点（%d 个）:" % len(leaves))
    for op, o in leaves[:30]:
        print("      %-12s %s" % (op, o))

    # 挑 DFL conv 和 Sigmoid
    dfl_nodes = [o for op, o in leaves
                 if "dfl" in o.lower() and "Conv" in o]
    sig_nodes = [o for op, o in leaves
                 if "Sigmoid" in o]
    print()
    print("    识别结果:")
    print("      DFL  conv  : %s" % (dfl_nodes or "❌ 没找到"))
    print("      Sigmoid    : %s" % (sig_nodes or "❌ 没找到"))

    if args.list_only:
        print()
        print("  （--list-only，到此为止）")
        return 0

    if len(dfl_nodes) != 1 or len(sig_nodes) != 1:
        print()
        print("  ⚠️ 无法唯一确定两个输出节点，检查上面的叶节点列表。")
        print("     通常 YOLO11 结构是固定名字，若变了需要人工指定。")
        # 兜底：按已知命名
        dfl_nodes = dfl_nodes or ["/model.23/dfl/conv/Conv_output_0"]
        sig_nodes = sig_nodes or ["/model.23/Sigmoid_output_0"]
        print("     尝试按已知命名兜底: %s + %s"
              % (dfl_nodes[0], sig_nodes[0]))

    out_names = [dfl_nodes[0], sig_nodes[0]]

    # ── 3) 裁剪 ──────────────────────────────────────────────────
    print()
    print("  [3/4] 裁剪输出节点 …")
    in_names = [i.name for i in graph.input]
    print("    输入: %s" % in_names)
    print("    输出: %s" % out_names)
    try:
        onnx.utils.extract_model(str(raw_onnx), str(crop_onnx),
                                 in_names, out_names)
    except Exception as exc:
        print("  ❌ extract_model 失败: %s" % exc)
        return 1
    print("  ✅ 裁剪 ONNX: %s  (%.1f MB)"
          % (crop_onnx.name, crop_onnx.stat().st_size / 1e6))

    # ── 4) 校验 ──────────────────────────────────────────────────
    print()
    print("  [4/4] 校验裁剪后的模型 …")
    try:
        import numpy as np
        import onnxruntime as ort
        sess = ort.InferenceSession(str(crop_onnx),
                                    providers=["CPUExecutionProvider"])
        x = np.zeros((1, 3, args.imgsz, args.imgsz), dtype=np.float32)
        outs = sess.run(None, {sess.get_inputs()[0].name: x})
        print("    ✅ onnxruntime 能跑通")
        for o, arr in zip(sess.get_outputs(), outs):
            print("       %-46s shape=%s dtype=%s"
                  % (o.name, arr.shape, arr.dtype))
        print()
        print("    ℹ️ shape 里的 8/16/32 是特征图尺寸，nc 应等于类别数")
    except ImportError:
        print("    ⚠️ 没装 onnxruntime，跳过数值校验")
    except Exception as exc:
        print("    ⚠️ 校验出错: %s" % exc)

    print()
    print("=" * 74)
    print("  ✅ 完成")
    print("=" * 74)
    print("  下一步（WSL 里）:")
    print("    bash /mnt/c/Users/29845/Desktop/工创赛/_deploy_maixcam/"
          "wsl_convert_%s.sh" % name)
    print("  （需要先按 templates 生成该脚本，或直接改 wsl_convert.sh 里的")
    print("    WORK / SRC_ONNX / NAME / CALIB_SRC 四个变量）")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
