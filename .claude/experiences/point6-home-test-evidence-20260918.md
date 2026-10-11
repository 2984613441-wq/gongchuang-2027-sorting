# HOME 变更后的主机断言与部署证据

- 日期：2026-09-18；来源任务 point6-audit-20260918。
- 证据状态：VERIFIED（仅本地主机测试和本地源码观测）；治理状态：DRAFT。
- Provider/运行时：Codex，Windows PowerShell，Python 3.14.5，MinGW GCC 16.1.0；没有 Raspberry Pi 运行验证。

## 五字段

1. **背景**：HOME 宏从负角坐标改为 (0,0)，测试仍断言旧步数；派工文档给出的新 Z 索引又与当前动作时序不符。Pi SSH 两次连接超时。
2. **问题**：只重算脉冲而忽略零位移腿省略，会使全部后续索引错误；把过期示例顺序当准则会让测试要求先搬运后夹取；本地 hash 不能证明远端部署一致。
3. **决策/机制**：只改 host 测试，按 abs(Δmm10)×8 独立计算；保留源码中的闭合→搬运→释放，省略 HOME=PICK 的 XY 两腿后整体前移两格；宿主 GCC 直接构建绕过 CMake 已知环境障碍；远端缺证据留空而不写 SAME。
4. **结果/证据**：旧测试编译 exit=0、运行 exit=1；修后 X-first/Y-first 与 axis-driver 均编译/运行 exit=0。见 docs/reports/2026-09-18-point6-evidence/host-red.json 与 host-green.json。7/7 生产源码/配置 MD5 不变。SSH exit=255，两端一致性 UNVERIFIED。
5. **适用/反例/禁用条件**：适用于运动规划纯逻辑回归及多 AI 并发时的快照审查；HOME/夹爪时序再变时需重读源码并重算，不能复制本次常数。主机通过不能支持实机安全/显示/串口通过，读取旧名称表也不能证明当前远端内容。首次完整运动尚未成功时不得借本轮测试恢复 DropPoints。

本记录不改变固件参数或治理规则，不自动采纳为新的生产控制策略。若源码 hash 或运行环境变化，降为 STALE 并重新核对。
