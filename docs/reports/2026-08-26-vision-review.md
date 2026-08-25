# 视觉初赛主链审核记录（2026-08-26）

## 结论一句话

初赛视觉主链（检测 -> 抠 ROI -> 形状 + 颜色 -> 分组 -> 映射 6 箱）可以运行，53 项测试全过；颜色主色提取确实借鉴了 node-vibrant 的 MMCQ，决赛信息插槽引用了 RapidOCR / OnnxOCR / zxing 的选型结论；本轮补上了 ROI 越界校验并落盘。

---

## 1. 审核范围

- `视觉/src/sorting_vision/color_quant.py`（新增）
- `视觉/src/sorting_vision/sort_plan.py`（新增）
- `视觉/src/sorting_vision/info_decode.py`（新增）
- `视觉/examples/sort_chain_demo.py`（新增）
- `视觉/tests/test_sort_plan.py`（新增）
- `视觉/src/sorting_vision/__init__.py`、`视觉/README.md`（修改）

未改动电控、树莓派、STM32、旧模型权重。未接串口、未上电、未烧录、未运动。

## 2. 能否运行

在仓库根目录执行：

```powershell
python -m unittest discover -s 视觉/tests -v
```

结果：`Ran 53 tests in 0.125s ... OK`（原有 45 项 + 新增 7 项 + 本轮补 1 项）。

```powershell
python 视觉/examples/sort_chain_demo.py
```

输出 6 组、6 箱，颜色与箱号映射正常；`info_decode` 返回 `InfoResult(qr_text=None, ocr_text=None, graphic_id=None)`。

```powershell
python 视觉/examples/fake_demo.py
python 视觉/src/sorting_vision/color_quant.py
```

均通过，只用 Python 标准库。

## 3. 是否借鉴了 GitHub 参考

- `color_quant.py` 是 `node-vibrant` 的 MMCQ 主色提取移植，注释写明对应 `histogram.ts`、`vbox.ts`、`index.ts`、`converter.ts` 四个源文件。已逐段比对原码，`split`、`avg`、直方图、RGB<->HSL 为忠实移植，Python 版额外加了数组边界保护。
- `info_decode.py` 引用 RapidOCR、OnnxOCR、`zxing-cpp`/`pyzbar`，并明确拒绝手抄 PHP/JS/ObjC 端口里的 Reed-Solomon。这些均在你给的参考清单内（`node-vibrant-main.zip`、`RapidOCR-main.zip`、`OnnxOCR-main.zip`、`zxingify-objc-master.zip`、`php-qrcode-detector-decoder-master.zip`、`vue-qrcode-reader-master.zip`、`ZXingLite-master.zip`）。
- 未引入 maskrcnn / CenterNet 等不必要组件，形状继续走现有 YOLO，符合“属性分离”方向。

## 4. 审核发现

| 级别 | 问题 | 处理 |
|---|---|---|
| 重要 | `crop_rgba`/`classify_and_plan` 不校验 bbox 越界，实测 `3x2` 图配 `bbox(0,0,5,2)` 返回 32 字节错乱数据而非报错 | 本轮修复 |
| 重要 | 颜色词表为 starter 映射，蓝/灰分界依赖 `s < 0.12`，物料恰为蓝+灰，需现场白平衡/光照标定后冻结 | 待现场标定 |
| 次要 | MMCQ 移植用 `int(0.75 * color_count)`，与原版 `0.75 * color_count` 浮点 target 有细微差，影响中间切分盒数，不影响 dominant 结果 | 记录不改 |
| 次要 | `crop_rgba` 硬编码 RGBA 四通道，真实相机（GC4653/MaixCAM）输出格式未定 | 接真机前明确 |
| 外观 | `__init__.py` 存在 LF/CRLF 行尾混用 | 记录不改 |

## 5. 本轮修复

`sort_plan.py` 的 `crop_rgba` 增加入参校验：

- `image_width`、`image_height` 必须为正整数，否则抛 `InvalidInputError`；
- 调用 `bbox.validate(image_width, image_height)`，越界或非法 bbox 抛 `InvalidDetectionError`，fail-closed。

新增测试 `test_crop_rgba_rejects_out_of_image_bbox`，确认越界 bbox 被拒绝。

## 6. 待办与未冻结

1. 颜色 HSV/HSL 阈值需现场标定后冻结，当前不可用于最终分拣判定。
2. 待补数据：球、圆锥、正四面体等缺类，以及弱类 `cuboid`/`triangular_prism`。
3. 接真机前需明确图像像素格式（RGBA/RGB/BGR/YUV）与颜色通道顺序。
4. 决赛“信息”（文字/二维码/缺陷图形）仅保留 `info_decode` 插槽，未实现。

---

*本记录由 Codex 生成，未执行 `git commit`。*
