# 视觉代码优化变更说明

- **任务 ID**：task-vision-optimization-20261011
- **日期**：2026-10-11（执行时间 2026-10-12）
- **等级**：L2（单子系统、纯主机侧逻辑、可逆；不改协议、不改公共 API 签名）
- **依据提示词**：`.claude/sessions/task-vision-code-optimization-prompt.md`
- **执行记录**：`.claude/sessions/task-vision-optimization-record-20261011.md`

---

## 改动汇总

| 项 | 数量 | 文件 |
|---|---|---|
| 新建（源码） | 2 | `视觉/src/sorting_vision/constants.py`、`视觉/src/sorting_vision/shape_features.py` |
| 新建（测试） | 2 | `视觉/tests/test_constants.py`、`视觉/tests/test_shape_features.py` |
| 修改（源码） | 5 | `视觉/src/sorting_vision/config.py`、`pipeline.py`、`single_target.py`、`drop_table.py`、`__init__.py` |
| 修改（文档） | 1 | `视觉/README.md`（模块表补 2 行 + 新增"轮廓形状兜底（未接入）"小节） |
| 删除 | 0 | — |
| 测试结果文件 | 1 | `视觉/test_results.txt` |

⚠️ 提示词写的是"新建 2 + 修改 3"。实际多改了 3 个文件（`drop_table.py`、`__init__.py`、`README.md`），多建 2 个测试文件。原因见下方【与提示词的偏离】。

---

## 改动详情

### 1. 新建 `constants.py`（P0-1：提取魔法数字）

集中 10 个原先散落的字面量，并按来源标注 `PROTOCOL`（协议冻结）/ `TUNABLE`（经验默认）：

| 常量 | 值 | 来源 | 原先散落处 |
|---|---|---|---|
| `MAX_TASK_ID` | 65535 | `interface-contract.md` uint16 | `pipeline.py:21,24` |
| `MAX_TARGET_SEQ` | 255 | `interface-contract.md` uint8 | `pipeline.py:98,101` |
| `COORDINATE_BOUND_MM10` | 1450 | `interface-contract.md:163-164` | `drop_table.py:17` |
| `MAX_DETECTIONS_SINGLE_TARGET` | 100 | 经验值 | `single_target.py:128` |
| `DEFAULT_MAX_DETECTIONS_BATCH` | 100 | 经验值 | `config.py:21` |
| `DEFAULT_CONFIDENCE_THRESHOLD` | 0.50 | 经验值，**未标定** | `config.py:17` |
| `DEFAULT_NMS_IOU_THRESHOLD` | 0.45 | 经验值 | `config.py:18` |
| `DEFAULT_INPUT_WIDTH/HEIGHT` | 448 | `视觉/README.md:20`、`TRAINING.md:60` | `config.py:19`、`single_target.py:54-55` |
| `MIN_CONTOUR_AREA_PX` | 100 | 归档轮廓脚本 | 原为 `shape_features.py` 内字面量 |

模块本身**零依赖**（不 import numpy / cv2 / 模型运行时），因此任何 `sorting_vision` 模块和 MaixCAM 侧脚本都能安全 import。

### 2. 新建 `shape_features.py`（P0-3：集成形状特征分类器）

提供 4 个入口：

- `extract_contour_features(contour) -> ContourFeatures`：测量几何描述子（面积/周长/凸包/实心度/圆度/多边形角数/最小外接矩形比值与充满度/四角余弦/椭圆面积比）。
- `classify_shape_from_features(features) -> str`：**纯算术，不依赖 OpenCV**，因此在没有 cv2 的机器上也能跑测试。
- `extract_and_classify_roi(roi_bgr, lower, upper, *, extra_ranges=(), min_area=...)`：颜色分割 → 最大轮廓 → 分类；无有效轮廓返回 `None`。
- `rgba_roi_to_bgr_array(pixels, w, h, bbox)`：把 `sort_plan` 使用的扁平 RGBA 缓冲裁成 `HxWx3` BGR 数组——这是接入主链唯一缺的那段适配器。

**规则来源**：`archive/_B档金贵-20261002/视觉V6-03_历史版本与验证/stage1_contour_v3.py` 的 `shape_from_contour`（第 45–83 行），阈值逐条搬运：

- 实心度 `area/hull_area < 0.90` → `unknown`
- 三角形：`approxPolyDP(0.035·perimeter)` 得 3 点且凸、最小外接矩形比值 ≥ 0.50、三角形覆盖 ≥ 0.78·area → `triangular_prism`
- 正方体：`approxPolyDP(0.025·perimeter)` 得 4 点且凸、矩形比值 ≥ 0.74、矩形充满度 ≥ 0.84、四角最大 |cos| ≤ 0.35 → `cube`
- 圆柱：多边形角数 ≥ 5、圆度 ≥ 0.80、矩形比值 ≥ 0.68、点数 ≥ 5、`area/拟合椭圆面积 ∈ [0.90, 1.08]` → `cylinder`
- 其余 → `unknown`

**能力边界（重要）**：该几何法只能区分"平面朝上"的 3 类（cube / cylinder / triangular_prism），无法区分投影相同的形状，也**不尝试**另外 4 类（cuboid / hexagonal_prism / pentagonal_prism / square_pyramid）。没有标定数据就为它们编阈值，比返回 `unknown` 更糟。`unknown` 不是词表里的类。

### 3. 统一置信度阈值（P0-2）

`SingleTargetLoopConfig.confidence` 默认值 `0.35 → DEFAULT_CONFIDENCE_THRESHOLD (0.50)`，与 `InferenceConfig` 一致。

**这是本次唯一的行为变更**：置信度落在 `[0.35, 0.50)` 的检测原先会通过单目标循环，现在被过滤。`test_single_target.py` 用 0.20 / 0.80~0.95，未被影响；仓库内没有生产代码用默认值构造 `SingleTargetLoopConfig`。**仍需现场光线复核后才能定稿**。

### 4. 消除重复代码（P1）

`pipeline.py` 新增 `_safe_int(value, fallback)`，替换 4 处 `x if isinstance(x, int) else -1`；`MAX_DETECTIONS` 字面量删除，改为 `MAX_DETECTIONS_SINGLE_TARGET` 的兼容别名。

### 5. 单一真相源（超出提示词，见「偏离」）

`drop_table.py` 的 `ITEM_TASK_COORD_LIMIT = 1450` 改为从 `constants.COORDINATE_BOUND_MM10` 再导出，名字保留（`from sorting_vision.drop_table import ITEM_TASK_COORD_LIMIT` 仍然可用）。避免同一协议数值出现两处定义。

---

## 测试结果

同一解释器（`py -3`，Python 3.14.5）前后对比：

| | 收集 | passed | failed | skipped |
|---|---|---|---|---|
| **改动前基线** | 115 | 81 | 9 | 25 |
| **改动后** | 186 | 133 | 9 | 44 |

- **9 个失败用例的 node id 集合前后完全一致**（已用 `Compare-Object` 逐条比对）：**0 个新增失败、0 个被掩盖**。
- 9 个失败全部是**改动前既有**的，与本次改动无关：
  - 8 个是环境问题——`tempfile.TemporaryDirectory()` 在 DSH 文件沙箱下 `PermissionError`（`test_backends_and_config.py` 6 个 + `test_prepare_voc_dataset.py` 2 个）。已单独验证：不经沙箱直接用 `tempfile` 同样失败，与本改动无关。
  - 1 个是**真实的既有源码/测试漂移**：`test_stage1_color_v6_pose.py::test_60`，源码 `MIN_COLOR_FRACTION=0.6`，测试注释写 0.7。
- 新增 71 个测试：**52 passed + 19 skipped**（跳过的是需要 OpenCV 的 19 个）。
- 另用 Python 3.11.15 + `opencv-python-headless 5.0.0.93` 实跑新增测试：**71 passed, 0 skipped**——即 19 个 OpenCV 测试是**真跑通**的，不是靠 skip 掩盖。
- 退化输入已用真实 cv2 实测：1 点 / 2 点 / 3 点共线 / 4 点共线轮廓均返回 `unknown` 而不抛 `cv2.error`；`(N,2)` 与 `float32` 轮廓正常接受；合成三角形 (10,10)(90,10)(50,80) 判为 `triangular_prism`。这些已固化为回归测试。
- **10 个阈值边界测试**：每个边界夹具的判据值**精确等于**对应阈值（已逐个验证 `metric == threshold` 为真），因此把任一 `>=` 改成 `>` 都会令该测试失败——不是"碰巧通过"。

> ⚠️ **提示词里的验收标准"62 passed"无法达成**：改动前实际收集 115 项（就已是 81 passed / 9 failed / 25 skipped），不存在"62"。该数字疑似来自 `test_stage1_color_v6_pose.py` 中 `test_60`~`test_65` 的用例编号。本次以"失败集合不扩大"作为真正的验收口径。

## 独立对抗性复核（两轮）及其修复

两名独立复核者（只读）分别审查了全部改动，结论一致：**常量重构、`_safe_int` 等价性、公共 API 与协议冻结这三部分判定为行为保持且合规**，但 `shape_features.py` 有两处真问题。已全部修复：

| 复核发现 | 严重度 | 处理 |
|---|---|---|
| `extract_contour_features` 只校验形状不校验 dtype：`float64` / `uint8` / `int16` / `uint16` / `bool` / 非连续视图 都会让 `cv2.error` 逃逸，违反其 docstring 承诺（"只抛 `InvalidInputError`/`DependencyUnavailableError`"）。已实测复现 | MAJOR | 在形状校验后归一化为连续 `float32`（`np.ascontiguousarray`），并把 `TypeError/ValueError` 转成 `InvalidInputError`；新增 8 种 dtype + 非连续视图的回归测试。选 `float32` 而非 `int32` 是为了不截断亚像素坐标 |
| **光滑正六边形被判为 `cylinder`**——`hexagonal_prism` 是 7 类词表里的真实类，这是"自信的错答案"。而代码注释声称 0.90–1.08 椭圆带"能排除六边形轮廓"，实测（circ 0.824 / 矩形比 0.875 / 椭圆比 0.962）**恰好推翻该说法**。该行为逐字继承自归档脚本（它没见过六边形） | MAJOR | 修正注释与 docstring 为实测事实；新增 `test_smooth_hexagon_is_currently_named_cylinder` 把这一已知错误答案**钉在代码里**，使其不会被静默改动。**没有**为六边形新造阈值（那会违反"无标定数据不猜阈值"的原则） |
| "归档脚本在真机上跑过、检查就在旁边"——过度声称。`stage1_contour_checks/results.json` 自述 `"This is not raw-camera or on-device verification."` 且记录 `host_opencv: 5.0.0`；`stage1_v3_color_first_checks.json` 属于"颜色优先"变体，用例写的是 "same contour, **mapped shape**"，根本没跑 `shape_from_contour` | 过度声称 | docstring 逐条更正为"主机侧截图检查，非真机验收"，并说明那份 colour-first 检查与本节规则无关 |
| `MIN_CONTOUR_AREA_PX = 100` 声称"与归档最小面积门一致"——**假**。归档门是相对值 `0.0015..0.22 × 帧面积`（320² 下为 153.6..22528 px） | 过度声称 | `constants.py` 改为如实说明：100 是任务提示词给定值，无法用固定像素复现相对门，属**有意近似**而非移植 |
| `COORDINATE_BOUND_MM10` 声称"整个仓库只此一处"——**假**，`电控/src/electrical_control/protocol/item_context.py:101` 另有 `_ITEM_TASK_X_LIMIT = 1450` | 过度声称 | 改为"在 `sorting_vision` 内唯一"，并注明电控侧另有一份、两值一致、统一属跨子系统改动不在本任务范围 |
| `test_constants.py` 声称能阻止"重新内联魔法数字"——它只比较**值**，把 `DEFAULT_CONFIDENCE_THRESHOLD` 换回字面量 `0.50` 仍全绿 | 过度声称 | docstring 改为如实限定：只防"漂移"，防不了"重新内联"；并说明需要源码/AST 扫描才能验证"确实读的是常量" |
| 测试对阈值**不敏感**：把 9 个 `>=` 全改成 `>`，16 个夹具**无一改变结果**，即移植的"不等号方向"完全没被测到 | MINOR | 新增 `ThresholdBoundaryTests`（10 个边界），每个夹具的判据值**精确等于**阈值（已逐个验证 `metric == threshold` 为真），任一不等号方向改动都会失败 |
| `extract_and_classify_roi` 未移植归档脚本**围绕**分类器的门（贴边→unknown、相对面积门、形态学开闭），但 docstring 以"移植路径"呈现 | MINOR | docstring 明确列出**故意不移植**的三项及理由（紧裁剪框必然贴边；相对门无固定像素等价；形态学是按整帧调的），要求调用方自行做预处理 |
| `rgba_roi_to_bgr_array` / `_merge_hsv_mask` 会漏出 `AttributeError`/`TypeError`/`OverflowError`，而它们已进入 `__all__`（公共面） | MINOR | 加校验：bbox 四个数值属性、`pixels` 可 `len()`、bool 不当整数、HSV 三分量 0..255；全部转 `InvalidInputError` |
| 空裁剪图 `(0,0,3)` 会通过形状校验后被 `cv2.cvtColor` 抛 `cv2.error` | MINOR | 显式拒绝空裁剪 |
| `fitEllipse` 由"惰性"变"急切"（每个 ≥5 点轮廓都拟合），且 `cv2.error` 被静默吞成 0.0 | NIT | 恢复归档的惰性：仅在圆柱分支的廉价前置条件满足时才拟合（分类结果不变，省掉每轮廓一次拟合）；吞异常的语义写明为"失败即退到 `unknown`"（安全方向） |
| `drop_table.py` docstring 仍写 "Protocol V0.6"，而现行契约是 V0.9 | NIT | 更正为 V0.9（只改注释，数值未动） |

**未采纳的复核意见**：`triangle_area/area >= 0.78` 与归档 `triangle_area >= 0.78*area` 存在 1 ulp 差异（NIT）。要完全消除需改动公开的 `ContourFeatures` 字段，风险大于收益，故保留并在此登记。

完整输出：`视觉/test_results.txt`（含 OpenCV 版本附录）。

---

## 与提示词的偏离（逐条说明）

| # | 提示词要求 | 实际情况 | 处理 |
|---|---|---|---|
| D1 | "62 项 unittest 全部通过" | 实际 115 项，基线 9 失败 | 改为"失败集合不变"；已在上节说明 |
| D2 | 形状代码在 `视觉V6-01_当前运行_V6/stage1_color_v6_stable.py` 约 150–200 行 | **该文件没有形状分类器**：其 docstring 明写"不测量轮廓形状"，第 111 行 `shape, bin_id = COLOR_TO_MATERIAL[color]`，轮廓代码只做面积/外接矩形**过滤** | 改从真正含分类器的 `stage1_contour_v3.py` 移植 |
| D3 | 提供 `circularity>0.85→cylinder` 等一套阈值，称"ported from stage1_color_v6_stable.py" | **归档区任何文件都没有这套阈值**，属凭空杜撰 | 弃用；改用归档区真实阈值（见改动 2），逐条可核对 |
| D4 | 修改 `sort_plan.classify_and_plan` 接入形状回退 | 真实签名是 `classify_and_plan(pixels, image_width, image_height, detections, box_count, vocabulary, box_assignment)`——收扁平 RGBA，**没有 `image` 参数**，也没有 `color_vocabulary` 形参；提示词给的代码无法套用 | **未接入主链**。提示词自己的验收清单也写"即使未集成到主链"，集成列为 P1/可选。已提供唯一缺的适配器 `rgba_roi_to_bgr_array` 并测试通过，接入留待单独决策 |
| D5 | 为何不接入 | 该核心的形状来自 YOLO `class_id`，而 `class_id` 决定箱号 = 决定物理落料盒。用几何猜测**静默覆盖**它，会改动已要求现场冻结的物理映射；提示词给的集成片段本身是 `except Exception: pass` 的静默空操作，比不接更危险 | 记录为待决策项，见【遗留问题】 |
| D6 | `constants.py` 含 `COORDINATE_BOUND_MM10 = 1450` | 该值**已存在**于 `drop_table.ITEM_TASK_COORD_LIMIT`，照抄会造成第二份真相 | 字面量移入 `constants.py`，`drop_table` 再导出，名字不变 |
| D7 | 删除 `MAX_DETECTIONS` 那一行 | 删除会破坏潜在的仓外引用 | 改为常差别名，字面量确实只剩一处 |
| D8 | 只改 3 个文件 | 需要额外改 `drop_table.py`（D6）、`__init__.py`（导出新模块，纯新增）与 `README.md`（模块表登记新模块 + 明确标注"未接入主链"，防止后来者误以为已接） | 已登记在上表 |
| D9 | "OpenCV 已存在，可用" | 主机 `py -3` **没有 cv2** | 未安装任何东西；经用户授权使用工作区已有的 `.uv-test-cache\vision-test-env` 实跑 OpenCV 测试 |

---

## 遗留问题

1. **省赛真正的 P0 没有被本次改动解决。** `视觉/src/maixcam_deploy/stage1_color_v6_send.py:409` 仍是 `shape, bin_id = COLOR_TO_MATERIAL[color]`——形状是**查色表查出来的**。`docs/交接总纲-20261002.md:291` 已把它列为 ★★★★★ 风险：省赛 24 件必然出现同色不同形/同形不同色 ⇒ 必然分错盒。`sorting_vision/shape_features.py` 是本机纯逻辑核，**不会自动改变 MaixCAM 上的行为**。
   修它属于改动**已部署的生产链**，且有 `tests/test_stage1_color_v6_pose.py` 的契约测试守着，风险等级高于本任务 ⇒ 需要单独授权与单独评审。
2. **形状特征阈值全部未标定**，需现场光线/白底/俯视固定机位下重新核验；当前只是"假设生成器"，不是标定测量。
3. **已知会给出"自信的错答案"的具体情形**（复核实测，已写进代码与测试）：
   - 光滑**正六边形 → `cylinder`**、正八边形 → `cylinder`，而 `hexagonal_prism` 是 7 类词表里的真实类；这是归档规则自身的能力边界，未新造阈值去补。
   - 因此**不能**把该模块的输出当作"不是圆柱就是正方体或三棱柱"的证据；只有 `unknown` 是可靠的安全输出。
4. **`confidence` 默认值 0.35→0.50 未做实机验证**（行为变更，见改动 3）。
5. **主链接入未做**（D4/D5）：若要接，建议设计成**显式开启、不改箱号**的交叉校验/告警，而不是静默覆盖；并且应作 L3 处理（影响分箱决策与物理映射）。
6. **既有未修问题（本次未动）**：`test_stage1_color_v6_pose.py::test_60` 的 `MIN_COLOR_FRACTION` 0.6 vs 0.7 漂移。本次改动未触碰该文件，是否修需另定。
7. `.uv-test-cache\`（约 479 MB）是本次执行期间工作区里出现的测试环境目录，经用户同意保留；它未被 `.gitignore` 覆盖。
8. **并发写入事件**：执行期间有另一个会话/进程同时修改本任务的同一批文件——它曾把 `constants.py` 从约 3.8 KB 覆盖为 354 B（清空了全部来源注释）、新建过一版 `tests/test_shape_features.py`，并在 22:59 生成两份变更/审查文档。经用户确认由本会话独占写入后，已恢复注释、合并两版测试，并把那两份文档更正为指向本说明的留痕（**未删除**；删除需另行授权）。它同时补上了 `tests/test_constants.py` 缺失的 `FakeBackend` import（该缺失原本会导致 5 项 NameError），此处如实记录来源。最终交付前应确认没有第二个写入者。

---

## 验证与回滚

**验证命令**

```powershell
cd "C:\Users\29845\Desktop\工创赛\视觉"
py -3 -m pytest tests/ -q -p no:cacheprovider                 # 主口径：9 failed / 133 passed / 44 skipped
& ..\.uv-test-cache\vision-test-env\Scripts\python.exe `
    -m pytest tests/test_shape_features.py tests/test_constants.py -q -p no:cacheprovider   # OpenCV 实跑：71 passed
```

> `-p no:cacheprovider` 是必需的：工作区里的 `.pytest_cache` 在沙箱下不可写，加上它可避免伪造失败。

**回滚**：删除 `视觉/src/sorting_vision/constants.py`、`视觉/src/sorting_vision/shape_features.py`、`视觉/tests/test_constants.py`、`视觉/tests/test_shape_features.py`、`视觉/test_results.txt`、`视觉/CHANGELOG_20261011.md`；恢复 `config.py` / `pipeline.py` / `single_target.py` / `drop_table.py` / `__init__.py` / `README.md` 的改动。本改动未触碰协议文档、模型权重、固件、接线，无不可逆动作。
