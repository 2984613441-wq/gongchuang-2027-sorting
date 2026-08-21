# REVIEW-20260820-002 · Codex 对 Claude P1-1 的采纳与整改记录

> 记录方：Codex（工程实施；本记录不构成独立审核）
> 依据：REVIEW-20260820-001-claude-barrier-command-v1.md P1-1
> 日期：2026-08-20

## 结论

- P1-1（60s 计数超时静默截断）：采纳并完成整改。
- P2/P3 发现项：本次未处理，保留为后续候选，不视为已采纳。

## 整改内容

- `ec_step_test.h/c`：新增 `ec_step_result_t`（NONE/DONE/TIMEOUT）与 `ec_motion_test_step_result()`。
- 超时由固定 60s 改为 `(steps*1000)/frequency_hz + 1000 ms`，按运动参数推导。
- 完成回调置 DONE，超时路径置 TIMEOUT；新一次 MOVE STEPS、旧版 MOVE、STEP STOP/STOP ALL 清回 NONE。
- `ec_diag.c` STATUS 新增 `STEP_RESULT=%u` 字段。

## 验证

- 主机测试在 `%TEMP%` 纯英文目录全新构建：`ec_firmware_host_tests`、`ec_diag_disabled_tests` 2/2 通过。
- 新增测试：start 后 RESULT=NONE、完成回调后 DONE、超时边界（5999ms 未触发、6000ms 触发）TIMEOUT、STOP 清 NONE、STATUS 输出 STEP_RESULT。

## 边界

- Keil 命令行已重建（退出码 0），新 HEX SHA256 为 `A977A9FA20FC837A10401FEEE2DE42382C6F888D977DF8DAD65AFE4E69A458DE`；构建日志未落盘，0 Error(s)/0 Warning(s) 未以日志文本复核。git 提交未完成。
- 实机门禁不变：未授权不接线、不上电、不烧录、不运动。
