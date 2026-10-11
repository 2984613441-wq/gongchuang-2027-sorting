# 视觉链路证据独立复核（2026-09-18）

审查者：`/root/evidence_review`，与执行者为不同 agent 实例、同模型。**弱独立性 — 需用户裁决**；本文仅提供技术建议，不批准治理状态变更或任何设备/外部动作。审查范围是主机只读核查与报告证据，不是固件、相机、串口、屏幕、运动或实机验收。

## 审查范围与方法

已读项目/全局治理、§0 基线与点1全文、B-07/V-12/V-21、`Codex-review-and-evidence` 技能；审查现有生产源码、`chain_probe.py`、原始运行输出、`dataset_models.py`、数据/模型附件和标定附件。未再次运行既有测试，未连接设备，未执行 git，未改任何生产文件。

本文简写：`E`=`docs/reports/evidence/vision-chain-20260918/`；`S`=`视觉/src/maixcam_deploy/stage1_color_v6_send.py`。所引行号均为审查时文件行号。

## 已核实的证据有效性

1. **主机链路探针确实调用生产实现。** `E/chain_probe.py:21-24` 直接导入生产 ITEM_TASK 编解码、BATCH 解析、TCP 数据区分帧和像素换算；`:31-40` AST 提取完整函数/类并打印源 SHA256，`:50-59` 提取现有 main/V6/bridge 编码器，`:134-143` 调用真实 `build_socket_source` 与许可消费。它没有重写一份编码器来证明自己；注入的大小、角度与追踪常量和 `S:43-44,169-172` 一致。原始向量、两边解析结果、异常拒绝及退出码见 `E/chain-probe-output.txt:25-31,51`。

2. **校赛 id 后半链复现有效，但不等同于图像识别。** `S:49-62` 将 `bin` 编为唯一 id 字节；`电控/src/electrical_control/rpi/vision_ingest.py:117-118` 同时赋给 `class_id`、`box_id`，`:231,250-251` 分别用于落点和 ITEM_TASK/图片身份。探针中的 `row()` 固定 `color=cyan,shape=cube`（`E/chain_probe.py:43-44`），六个 bin 测试证明的是 id 后半链；真正颜色到 bin 的依据是 `S:193-196,264-268`，不能把合成 row 当现场六色识别样本。

3. **数量上限与追踪复现的范围明确。** `S:269-271` 每色只选最大候选，`:284-287` 以 color 为唯一轨迹键，故生产 analyze 最多六种颜色各一件；`E/chain-probe-output.txt:33-34` 复现确认/HOLD/过期与两个同色 row 合并。后者是直接调用 tracker 的人工输入，生产 analyze 在此前已经限为每色一件；它不提供泛化多目标计数精度。

4. **空帧缓存发现成立，属于主机逻辑行为。** `S:134-137` 在网络 enable 分支之前就跳过空帧，因而探针 `enable=False` 不影响该分支结论。`电控/src/electrical_control/rpi/socket_vision_source.py:117-130,227-231` 仅有许可位、消费清空与新批次覆盖，没有过期时限；`E/chain_probe.py:148-157` 和输出 `:46` 支持“旧非空批次在空帧未发送后仍可被下次许可消费”。不能据此声称实机已重复抓取。

5. **名称和坐标配置复现必须限定到本地选定文件。** 探针显式加载 `工具/generated_names.json`（`E/chain_probe.py:118`），`电控/deploy/run_chain.py:487-497` 的真实模式要求启动者传入名称路径。测试中相容的名称不能证明设备实际选择了该表。该文件 `:697-708` 的已加载粗标参数优先于固定抓取点；输出 `E/chain-probe-output.txt:35,42` 是本地配置读出和主机换算，不是精度验收。

6. **ONNX 证据来自二进制，不是 README。** `E/dataset_models.py:153-166` 直接读取模型 protobuf 的 opset/IR，并通过 ONNX Runtime CPU session 的 inputs/outputs/metadata 取值；`E/dataset-models-output.txt:302-305` 留下实际三模型 I/O、七类内嵌顺序和 SHA256。没有调用 `session.run()`，故“加载成功”不能写成推理精度通过。输出内既有导出资产的 448 张量尺寸不改变本任务 320×320 的现场帧约束。

7. **B-07 反证强于旧台账的取值范围推断。** REMAP 是 0–6 的置换（`视觉/training/remap_labels.py:21`），因此编号仍在0–6不能证明语义统一。相同图片 hash/框坐标、64对全部严格满足 REMAP（`E/dataset-models-output.txt:147`），且 preliminary 的211份原有标签全部与原始采集归档相同（`:299`），足以推翻“preliminary全部已经统一”的现有依据。它仍不代替逐图形状真值验收，不能声称所有211份的实际形状都已逐图确认。

8. **测试结果未隐藏失败。** 两次主机 pytest 的权限错误保留于 `E/related-tests-output.txt`、`E/related-tests-workspace-output.txt`；最终同六个文件成功输出为 `E/related-tests-verified-output.txt:3,9,12` 的实际命令、`103 passed in 0.89s` 与 `exit_code=0`。`E/bridge-selftest-output.txt:9,12` 的18项通过是 host selftest，不能升级为MaixCAM/实机通过。

## 已提交执行者的报告边界建议

- `main.py:378-381` 与 `capture.py:55-63` 都按模型输入尺寸建相机；硬编码320的是V6。报告须分开历史源码入口和当前交接路线，设备此刻具体启动脚本/hash仍证据不足。
- 同色合并测试、六bin身份测试都使用合成字典，不能声称实测识别准确率或实际全场计数已通过。
- generated_names、六个临时同落点、配置 `is_calibrated=True` 分别是指定本地表、临时配置、参数可加载；不能升级为现场名称表已切换、六货格空间已分开、正式标定完成。
- 空帧跳过加 latest无TTL属于可复现源码缺口，保留问题证据即可；本次没有越界修协议或设备代码。

## 最终正文审查状态

已读 `docs/reports/视觉链路核对-2026-09-18.md` 全文，并对逐字段表、逐跳身份、计数、B-07反证、ONNX输出和现场清单作抽核。以上四类边界建议已体现在正文 `:25,45,106,119-121,129,157,165-187,195-205,234-236`。未发现阻塞本次主机证据交付的事实错误；这是一项技术建议，不是实机验收或台账裁决。

另提交一项低影响措辞修订并已复读确认落盘：正文 `:87` 现为“发送器在运行时却跳过空批；Pi因未收到空批而不会清空既存候选，且没有批次时间有效期”。Pi真实解析器接受空批（`E/chain-probe-output.txt:27`），修订后不再把发送端不发说成接收端不支持空批。未遗留需修改的报告问题。

## 审查时源码新鲜度读取

在工程根目录实际执行以下只读 PowerShell 命令，退出码0；三份哈希与 `E/chain-probe-output.txt:22-24` 一致。

```powershell
foreach ($visionAuditPath in @('视觉/src/maixcam_deploy/main.py','视觉/src/maixcam_deploy/stage1_color_v6_send.py','视觉/src/maixcam_deploy/v6_bridge.py')) { $visionAuditHash = Get-FileHash -Algorithm SHA256 -LiteralPath $visionAuditPath; Write-Output ($visionAuditPath + ' ' + $visionAuditHash.Hash) }
```

原始输出：

```text
视觉/src/maixcam_deploy/main.py 8F1A4BCE0E40F699345E66B266F1EBCF937686336945C9444BD4CBBEC9355E81
视觉/src/maixcam_deploy/stage1_color_v6_send.py D750BD2672062B081F21C3E85C5A300062ED4C7CEA84076AAD17330123DEAE41
视觉/src/maixcam_deploy/v6_bridge.py FA83E64BCCA7DAD9EE2F9B1EB7FF2050EDF0D8FB9D9DB9843E7C9930EF922CB5
```

## 定量评估与限制

证据有效性置信度：4/5。已审附件中发现的未披露证据缺失：0；已审附件中未限定的逻辑跳跃：0。明确仍缺失的外部验证分为4组：设备实际运行入口/hash、现场六色/多件识别真值、正式坐标/仓位标定、物理分拣与显示闭环。它们是本次主机审查的边界，不是测试通过可以消除的缺口。
