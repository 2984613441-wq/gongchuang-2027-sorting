# 像素到毫米标定接入（L2，2026-09-18）

目标：在树莓派主机链路注入可信抓取点，拒绝假标定，围绕 nadir 补偿视差。用户已明确授权本地代码、测试与证据修改；不部署，不接硬件。

【核心角色／执行官】
- 现有 SocketVisionSource 已有可选回调与透传；run_chain.build_socket_source 未注入。
- ObjectHeights 按 box_id 查询；class_id 与 box_id 不可混同，测试需故意使用不同值。
- 修复默认配置路径重复“电控”、INI 行尾注释造成高度丢失、全零/退化/非有限/量级异常参数接受的问题。
- 使用仿射像 A(160,160,1) 作为 nadir，保持用户指定的 H/(H-h) 补偿方向。

【辅助角色／建制官】
- 工厂将 PixelToDeviceConverter 转为 VisionTarget -> mm10 | None；转换器仍保留 class_id 关键字兼容，但明确其历史命名实际表示高度表 box_id。
- SocketVisionSource 缺省 None 保持原有不可序列化行为；正式组装始终注入转换器，失败转换会使该件不入队。
- 未配置高度不再猜 h=0，只有显式配置 0 才表示零高度；错误配置 fail-closed。
- 主点偏移没有现有实测证据，沿用用户明确要求的 320×320 中心假设，不引入新协议字段。

【监察角色】
- 范围：主机纯逻辑。协议、固件、GPIO、速度、Home、15 秒监控均不改。
- 不覆盖当前工作树其他人的改动。禁止修改三个指定 C 文件。
- 风险：数值合理性校验不能代替现场九点标定；主机通过不能声称实机运动通过。

【调度协议／执行决策】
单 Agent 实施和多角色内部复核，无外部写入。先写以下最小回归，再改实现，最后运行完整 pytest。

最小验证（修改前定义）：
1. 缺失/全零/退化/非有限/过大/过小仿射参数 -> 未标定，ERROR 含原因。
2. 未标定回调 -> None -> build_item_task_queue 空队列、SocketVisionSource 不产出，不抛异常。
3. 合成 A=[[0.5,0,-50],[0,0.5,-100]]，H=200，box_id=3 的 h=40：nadir=(30,-20)，像素 (180,120) -> (42.5,-45)mm -> (425,-450)mm10；旧公式得到 (500,-500)。
4. class_id=2、box_id=3 的高度选择；中心点在补偿后保持 nadir；边界/缺失高度/解析失败拒识且后续件继续。
5. 正式 build_socket_source -> Scheduler -> OutboundGateway -> FakeSerialLink，解码既有 ITEM_TASK 验证真实合成毫米抓取点，默认未注入仍拒绝编码。
6. 电控目录运行：`$env:PYTHONPATH='src'; py -3 -m pytest tests -q -p no:cacheprovider`。

基线首次运行：2 failed, 297 passed, 2 skipped, 59 subtests passed in 1.36s。两项失败均为 test_framebuffer_pack 在系统 TEMP 下 PermissionError，与本次待改代码无关；后续隔离临时目录复核。

完成状态：沙箱外基线 301 passed；新增 40 项回归后完整运行 341 passed, 59 subtests passed in 1.41s，退出码 0。主机独立脚本自检 8 项通过。工作区并行修改及最终行号、命令输出、受保护文件哈希复核详见 `docs/reports/2026-09-18-pixel-calibration-host-review.md`。本轮不部署、不验证实机运动。
