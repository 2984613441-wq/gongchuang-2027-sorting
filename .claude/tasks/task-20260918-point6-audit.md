# 点 6：启动门、部署 MD5、HOME 主机断言

- task_id: point6-audit-20260918
- owner: Codex /root；L2，单 agent 多角色内部审查。
- state: WAITING_EXTERNAL
- 用户授权：只读核对树莓派文件；修改 test_motion_plan.c 的旧断言；本地主机编译运行；文档证据。
- 禁止：改固件生产源码、改 DropPoints、烧录、运动、串口访问、启动链路、远端写入/删除/部署。
- 已读：项目/全局 CLAUDE.md、冲突台账、七点拆解 §0 与点 6。
- completed_milestones: 启动/运行期门与放行边界逐项列表完成；46 项本地探针记录；旧 C 断言先失败，修后 X-first/Y-first 及 axis-driver 均编译运行 exit=0；108 个本地文件 MD5 已保存。
- current_action: 本地交付已保存，远端 MD5 未完成。
- next_action: 恢复 SSH 后运行 docs/reports/2026-09-18-point6-evidence/audit_md5.py，补远端逐文件结果及实际 names/config；不重做已通过且未变化的主机测试。
- blocked_by: 两次 pi@172.20.10.8:22 SSH 连接超时（exit 255）。不是自动审批拒绝；没有远端读取结果。
- user_action_required: 恢复可连通的树莓派 SSH；若地址变化提供现用地址。已发异步信息问题，尚无回复。
- running_processes: 无。
- external_tasks: 无。
- interrupt_impact: 可安全中断；不操作硬件。
- artifacts: docs/reports/2026-09-18-point6-evidence/；最终报告 docs/reports/2026-09-18-点6编排部署与主机断言核对.md。
- evidence: host-red.json、host-green.json、gate-probes.json/output、local-md5-remote-unavailable.csv、ssh 两次 stderr、source-snapshot、test diff；7/7 生产保护文件哈希未变，测试源码与通过时快照一致。
- resume_from: 本任务记录与证据目录。

## 修改前最小验证

1. 用宿主 GCC、-std=c11 -Wall -Wextra -Werror -pedantic 编译 test_motion_plan.c + ec_motion_plan.c + ec_axis_driver.c，复现旧断言失败。
2. 仅修改 test_motion_plan.c，按 HOME=(0,0) 更新正/负落点与零位移用例；保留边界、驱动接收、Z 语义断言。
3. 同命令重新编译运行；另以 EC_MOTION_XY_ORDER_X_FIRST=0 验证已有 Y-first 分支，并运行相邻 axis_driver 主机测试。
4. 全程不执行 run_chain 真实入口、不访问任何串口/屏幕设备、不执行同步/隔离脚本；SSH 只执行标准库文件读取/MD5。
5. 修改前重读测试；保存生产源码/配置哈希前后，检测并发变更；不得覆盖他人修改。

## 已发现的输入冲突

- 七点提示词给出的 6 步 Z 位置与当前 ec_motion_plan.c:150–169 不一致。当前源码是 HOME→PICK、Z_DOWN、PICK→PLACE、Z_UP、PLACE→HOME，因此 PICK=(0,0) 时 Z_DOWN 在 step[0]，移动在 [1,2]，Z_UP 在 [3]，返回在 [4,5]。按实际源码保留闭合→搬运→释放顺序，仅前移测试索引。
- 读取七点文档与首次工作区检查并行时，误执行过一次只读 git status --short；发现 §0 禁令后不再执行任何 git 命令，无 git 写操作。

## 角色检查

- 核心角色：以当前代码/实际运行证据回答，不把旧文档当运行状态。
- 监察角色：无硬件/远端写操作，保持临时落点；主机通过不代表实机通过。
- 调度协议：现有授权内不依赖远端的工作均已完成；SSH 阻塞项明确保留，无待运行进程。

## PROGRESS_CHECKPOINT / 交付

- COMPLETED: ①门禁审查与配置/脚本实读；③主机测试旧断言修复与相关验证。
- WAITING_EXTERNAL: ②两端逐文件 MD5、远端配置/名称/历史目录实况。
- REVIEW: 单 agent 多角色内部审查；不声称独立第三方审查。
- 经验记录：.claude/experiences/point6-home-test-evidence-20260918.md（VERIFIED / DRAFT，仅主机边界）。
- 资源：无子代理、无外部应用写入、无固件镜像构建；验证采用宿主 GCC，不反复重试已知卡住的 CMake。
- 辅助脚本首版 TemporaryDirectory 遭遇沙箱 ACL 错误，已改持久化 fixture 后 46/46 探针完成；原错误留证。没有将工具自身错误归于被测项目。
- 本轮总 Token 数未由平台提供，不估报。
