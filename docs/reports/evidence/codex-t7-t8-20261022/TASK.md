# Codex T7/T8 任务与恢复台账

- task_id: codex-t7-t8-20261022
- owner: Codex（主执行）+ Embedded Firmware Engineer（只读独立复核）
- state: HOST_DELIVERED_LIVE_PENDING
- scope: GROUP/计数运动主机证据、五档提速评估；不改生产固件、协议、安全路径或他人文件。
- completed_milestones: 已读派工/治理/接口；冲突台账已在归档路径查阅；真实板级代码+模拟HAL证明GROUP重叠启动；复现五请求频率同走5000Hz峰值；严格警告探针构建；现有CMake七目标全部通过；85文件快照前后SHA256一致；主机交付报告已落盘。
- current_action: 主机交付已完成；实机仍待授权条件与现场证据
- next_action: Lead确认板上固件身份/GROUP编译开关，冻结实际速度/profile语义，另选安全中间位置再安排实机验证。
- blocked_by: 板上双轴波形/位移、实际档位及机械安全最高频率无本轮观测证据。
- user_action_required: 主机阶段无需；实机前确认位置、方向、整个运动包络和夹爪净空；不能从已标定远端直接试GROUP。
- running_processes: 无主机/硬件运行进程；构建均在TEMP，不删除临时快照。
- external_tasks: 无；独立审查完成，结果见 REVIEW.md。
- interrupt_impact: 安全；未执行串口、SSH、GPIO、烧录或运动命令。
- artifacts: docs/reports/2026-10-22-T7-T8-Codex-联动核验与提速方案.md；本目录。
- evidence: source-manifest.json、result.json、verification-transcript.log、probe-red.log、probe-green.log、probe-build.log、cmake-build.log、ctest.log。
- resume_from: 首先读报告摘要与未验证项，再确认目标板身份；不得直接以MOVE请求频率作为实测档位。
- 回滚: 本轮仅新增报告与独立探针，无生产代码需回退。不要还原工作树原有他人修改。

## 执行与失败记录

1. 初始探针连接缺少板级旁支依赖；补真实inputs/bus-servo模块及明确模拟HAL桩后编译通过。旧输出保留probe-build-first-failure.log，不是最终构建日志。
2. 模型曾把GPIO复用初始化当作“不可达”；真实夹爪启动需要该初始化，改为模型无操作。未改变生产代码。旧输出保留probe-model-first-failure.log。
3. Ninja在编译器ABI识别阶段停滞，已用该会话Ctrl-C中断；改为已有MinGW Makefiles生成器。无需更改系统权限或安装依赖。
4. 过长TEMP目录导致MinGW依赖文件路径失败；改短随机TEMP名并设CMAKE_OBJECT_PATH_MAX=200。旧输出保留cmake-longpath-first-failure.log。
5. 最终主机探针+构建+CTest退出0，7/7通过。速率反事实断言预期退出1，日志明确失败于请求频率不约束实际峰值；这不是生产行为已修复的证明。
6. 最终verify.ps1保存自身及源码快照并核对源文件前后哈希；如源变动，脚本会保存结果并失败，不宣称当前工作树验收。

