# 视觉代码优化任务 - 执行台账

**task_id**: task-vision-optimization-20261011
**owner**: DSH 会话（Lead 独占写入，2026-10-12 经用户确认）
**state**: COMPLETED（实现、验证、两轮独立对抗性复核及其修复均已完成）
**L 级**: L2（单子系统、主机侧纯逻辑、可逆、不改协议与公共 API 签名）
**依据**: `.claude/sessions/task-vision-code-optimization-prompt.md`
**交付说明**: `视觉/CHANGELOG_20261011.md`
**测试输出**: `视觉/test_results.txt`

---

## 一、关键事实校正（动手前核验，与提示词不符）

| # | 提示词说法 | 核验结果 | 证据 |
|---|---|---|---|
| F1 | "62 项 unittest 全部通过" | 实际收集 **115** 项；基线 **9 failed / 81 passed / 25 skipped** | `py -3 -m pytest tests/ --collect-only -q` → `115 tests collected` |
| F2 | 形状代码在 `视觉V6-01_当前运行_V6/stage1_color_v6_stable.py` 150–200 行 | 该文件**无形状分类器**，docstring 写"不测量轮廓形状"，`:111` 用 `COLOR_TO_MATERIAL[color]` 定形状；轮廓只做面积/外接矩形过滤 | 该文件 `:6`、`:88-89`、`:111` |
| F3 | 该文件含 `circularity>0.85→cylinder` 等阈值 | 归档区**无此阈值**，系杜撰 | 全库 grep 无命中 |
| F4 | 真正的形状分类器 | 在 `archive/_B档金贵-20261002/视觉V6-03_历史版本与验证/stage1_contour_v3.py::shape_from_contour`（`:45-83`） | 该文件 `:45-83` |
| F5 | `classify_and_plan` 可加 `image` 参数 | 真实签名为 `(pixels, image_width, image_height, detections, box_count, vocabulary, box_assignment)`，收扁平 RGBA，无 `image` 形参 | `视觉/src/sorting_vision/sort_plan.py:214-229` |
| F6 | `COORDINATE_BOUND_MM10=1450` 需新建 | 该值已存在于 `drop_table.ITEM_TASK_COORD_LIMIT` | `视觉/src/sorting_vision/drop_table.py:17`；协议 `docs/design/interface-contract.md:163-164` |
| F7 | "OpenCV 已存在，可用" | 主机 `py -3`(3.14.5) **无 cv2** | `py -3 -c "import cv2"` → `ModuleNotFoundError` |
| F8 | 省赛 P0 = "形状识别不存在" | 成立，但**在 MaixCAM 生产链**，不在 `sorting_vision` 纯逻辑核 | `视觉/src/maixcam_deploy/stage1_color_v6_send.py:409`；`docs/交接总纲-20261002.md:291` |

## 二、已完成里程碑（均有命令/文件证据）

| # | 里程碑 | 证据 |
|---|---|---|
| M1 | 基线固定：115 收集 / 9F 81P 25S，并逐条归因 9 个失败 | 基线存 `%TEMP%\vision_baseline_before.txt`；8 个为 DSH 沙箱 `tempfile` 权限问题，1 个为 `MIN_COLOR_FRACTION` 0.6 vs 0.7 既有漂移 |
| M2 | 新建 `constants.py`（10 常量，标注 PROTOCOL/TUNABLE 来源） | `视觉/src/sorting_vision/constants.py` |
| M3 | `config.py` / `pipeline.py` / `single_target.py` / `drop_table.py` 改用常量 | 4 文件；`_safe_int` 替换 4 处重复判断 |
| M4 | 新建 `shape_features.py`，从 `stage1_contour_v3.py` 逐条移植真实阈值 | `视觉/src/sorting_vision/shape_features.py` |
| M5 | 新增 52 项测试 | `视觉/tests/test_constants.py`、`视觉/tests/test_shape_features.py` |
| M6 | 无回归证明：9 个失败 node id 集合前后**逐条相同** | `Compare-Object` → `IDENTICAL failure sets` |
| M7 | OpenCV 实跑：52 passed / 0 skipped（Python 3.11.15 + cv2 5.0.0.93） | `视觉/test_results.txt` 附录 |
| M8 | 复核实跑抓出并修复 2 个**测试夹具**错误（`hull_area` 欠指定致 solidity 提前拦截）；另用真实 cv2 实测 1/2/3/4 点、共线、`Nx2`、`float32` 等退化轮廓，确认无 `cv2.error` 逃逸并固化为测试 | 修正后 52 passed |
| M9 | 最终全套件：`9 failed, 133 passed, 44 skipped`（收集 186），失败 node id 集合与基线逐条相同 | `视觉/test_results.txt:949` |
| M10 | **两轮独立对抗性复核**（只读 subagent，第二轮同步收取）。两者均判定：常量重构、`_safe_int` 等价性、公共 API 与协议冻结 = 行为保持且合规；`shape_features.py` 有两处真问题 | 复核报告全文见本节末"复核结论" |
| M11 | 修复全部 BLOCKER/MAJOR/MINOR：dtype 归一化（`cv2.error` 逃逸）、六边形→`cylinder` 的过度声称与注释、归档出处过度声称（非真机验收）、最小面积门出处、`1450` "全仓唯一"、`test_constants` 能力声称、**阈值边界不敏感**（新增 10 个精确边界测试）、ROI 未移植门说明、两个公共助手的异常泄漏、空裁剪、`fitEllipse` 惰性、`drop_table` V0.6→V0.9 | `视觉/CHANGELOG_20261011.md`【独立对抗性复核（两轮）及其修复】 |
| M12 | 边界测试敏感性**已证明**：10 个边界夹具的判据值精确等于阈值（`metric == threshold` 逐项为真）⇒ 任一 `>=`→`>` 都会失败 | 复核脚本输出；`ThresholdBoundaryTests` |
| M13 | 复核后全套件复跑：`9 failed, 133 passed, 44 skipped`，失败集合仍与基线逐条相同；OpenCV 环境 `71 passed, 0 skipped` | `视觉/test_results.txt` |

## 三、当前动作 / 下一步

- **current_action**: 已完成。两轮独立对抗性复核发现的问题已全部修复并复验。
- **next_action**: 无（本任务范围内）。若用户授权，下一步是 D4/D5 的 L3 接入评审，或生产链 `stage1_color_v6_send.py:409` 的形状识别改造。
- **blocked_by**: 无。
- **user_action_required**: 无（本任务范围内）。**范围外需拍板**：是否另行授权修 `stage1_color_v6_send.py` 的生产链形状识别（省赛真 P0）。

## 三·补、复核结论摘要

两轮只读复核（第二轮 `subagent` 同步收取，逐条给了 `file:line`）一致结论：

- **判定行为保持且合规**的部分：阈值数值逐条一致（0.90/0.025/0.035/0.50/0.78/0.74/0.84/0.35/0.80/0.68/0.90–1.08）、规则顺序 triangle→cube→circle 一致、`extent` 取自 `minAreaRect` 而非 `boundingRect`、`_safe_int` 与替换前逐字等价（含错误串 `[0, 65535]`/`[1, 255]`）、唯一运行时变更是 `confidence` 0.35→0.50、公共 API 与协议冻结值未动、`__all__` 只增不减、9 个失败确系既存环境问题（已由独立方法复现同一 9 个 node id）。
- **需修且已修**的两处 MAJOR：① 非 `int32/float32` dtype 与非连续视图会让 `cv2.error` 逃逸，违反自身 docstring；② 光滑六边形被判 `cylinder`，而代码注释声称椭圆带能排除六边形——实测推翻该说法。
- **未采纳**：归档 `0.78*area` 与本实现 `triangle_area/area >= 0.78` 的 1 ulp 差异（NIT）。消除它需改动公开 `ContourFeatures` 字段，风险大于收益，已登记。
- **复核者残余不确定**：无法在只读条件下重跑改动前基线（本会话有基线文件，已补上逐条 node id 比对）；未裁定 `MIN_COLOR_FRACTION` 的 0.6/0.7 谁对（不在本任务范围）；未打开 `.onnx` 核对 448×448。

## 四、并发与中断

- **running_processes**: 无（无长期后台进程；测试为同步短任务）。
- **external_tasks**: 本次执行期间发现**另一个会话/进程**在写同一批文件：曾把 `constants.py` 由 ~3.8KB 覆盖为 354B、新建过一版 `tests/test_shape_features.py`、并在 22:59 生成两份变更/审查文档（`视觉/视觉代码优化变更说明.md`、`docs/reports/2026-10-12-视觉代码优化-任务与审查.md`），其数字描述的是合并前中间态。用户已确认由本会话独占写入；已恢复注释、合并两版测试、并把那两份文档更正为指向权威说明的留痕（未删除，删除需另行授权）。最终答复前已重新确认 0 个新增失败。
  它同时补上了我 `tests/test_constants.py` 缺失的 `FakeBackend` import（该缺失原会导致 5 项 NameError），此处如实记录来源。
- **interrupt_impact**: 可随时中断。回滚 = 删除 4 个新文件 + `test_results.txt` / `CHANGELOG_20261011.md`，还原 5 个被改文件；无协议/硬件/模型改动，无不可逆动作。
- **artifacts**: `视觉/src/sorting_vision/constants.py`、`shape_features.py`；`视觉/tests/test_constants.py`、`test_shape_features.py`；`视觉/README.md`（登记新模块+标注未接入）、`视觉/test_results.txt`、`视觉/CHANGELOG_20261011.md`、本台账。
- **resume_from**: 重跑第二节 M6/M7 两条命令即可恢复验证状态。

## 五、范围内未做（及原因）

| 未做 | 原因 |
|---|---|
| 把形状回退接入 `sort_plan.classify_and_plan` 主链 | 提示词自己把集成列为 P1/可选；真实签名与提示词给的不符；`class_id` 决定物理箱号，静默覆盖会改动要求现场冻结的映射。已提供唯一缺的适配器 `rgba_roi_to_bgr_array`（已测）。接入应作 L3 单独决策 |
| 修 `stage1_color_v6_send.py:409` 生产链形状识别 | 属改动已部署生产链，有契约测试守着，风险高于本任务；需单独授权 |
| 安装 cv2 到主机 | 提示词称"OpenCV 已存在"但实际没有；不擅自改主机环境。经用户授权改用工作区已有 `.uv-test-cache\vision-test-env` |
| 修 `MIN_COLOR_FRACTION` 0.6/0.7 漂移 | 既有问题，不在本任务文件范围 |

## 六、验收口径（替代提示词中不可达的"62 passed"）

1. `py -3 -m pytest tests/ -q -p no:cacheprovider` 的 **failed node id 集合与基线完全相同**（0 新增失败）→ ✅ 已验证
2. `constants.py` 存在且被测模块实际引用 → ✅
3. `shape_features.py` 存在且函数可导入（`from sorting_vision.shape_features import ...` 及包级导出）→ ✅
4. 置信度默认值统一为 0.50 → ✅
5. 新增测试在**有 cv2** 的环境下全部真跑通（非 skip 掩盖）→ ✅ 52 passed / 0 skipped
6. 不改冻结协议、不改既有公共 API 签名、不删既有测试、不新增第三方依赖 → ✅（cv2/numpy 仍为可选导入，缺失时抛 `DependencyUnavailableError`）
