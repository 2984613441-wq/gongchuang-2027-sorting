# P9-A · 配置与部署一致性（🔨 实现者）

> **先读**：`../协作-2026-09-15/00-总览与交接规则.md`、
> `docs/冲突与决策台账-2026-09-10.md` 的 **E-14 / E-15 / E-16 / V-11**
>
> 你只做 **P9**。

---

## 要修的四处

### ① E-15：两份 `sorting_config.ini` 并存（**最影响工具**）

| | `电控/deploy/sorting_config.ini` | `电控/deployment/sorting_config.ini` |
|---|---|---|
| 大小 | **5052 B** | 2393 B |
| 节 | Vision / **Motion / Timeout / Safety / Calibration** / Network | Vision / Scheduler / Network / Debug |
| 置信度键名 | `confidence_threshold` | `conf_threshold` |
| 冻结参数 | **逐项命中全部冻结值**（80 / 165 / 82.5 / 145 / 无限位 / 180s / 标定日期） | **这七项一个都没有** |

**本节点已查明**：`deploy/` 是**现行**（唯一主链路运行器 `run_chain.py` 在那）。
台账曾判定"`deployment/` 是现行"，**那个判定是反的**（已在台账 §7.1 更正）。

**你要做的**：给**合并方案**或**防错方案**（改名 / 加 DEPRECATED 标记 / 加 README 指针）。
⚠️ 注意 `工具/control_panel.py` 默认指向 `deploy/` 那份，且它**不写死键名**
（直接列出文件里实际存在的条目）—— 所以合并不影响面板。

### ② E-16：两份调参手册互不兼容

`deploy/30秒快速调参指南.md` vs `deployment/30秒调参手册.md`，操作步骤不一致。
给处置方案。

### ③ E-14：`motion_config.json` 加载抛 TypeError

🔴 **先复现并定位根因**，再给修正方案。不要只看台账描述。

```powershell
cd C:\Users\29845\Desktop\工创赛
py -3 -c "import json,sys; ..."   # 自己找加载它的代码路径，复现报错
```
把**真实报错栈**贴出来。

### ④ `apply_config.py` 的假成功（**假成功比报错危险**）

`电控/deployment/apply_config.py:155-166`：

```python
def notify_scheduler(config):
    """通知树莓派调度器重新加载配置（热更新）"""
    # 当前简化实现：直接返回成功
    print_info("✅ 调度器配置已更新（立即生效）")     # ← 什么都没做
    return True
```

**现场调参的人会以为生效了。**

**你要做的**：
1. **先查清调度器实际怎么读配置**（`电控/src/electrical_control/scheduler/`）：
   启动读一次？每次任务读？
2. **二选一**：
   - 实现真热更新（SIGHUP / unix socket / 共享标志位）
   - 或**删掉假成功**，改成 `⚠️ 调度器不支持热重载，需重启服务`
3. **无论选哪个，都不能再打印"立即生效"却不做事。**

### ⑤ V-11：DEMO 夹具与六盒规模不符

`run_chain.py:109-112`：
```python
DEMO_NAMES = {2: "红方柱", 4: "蓝圆柱"}            # 只有 2 个名字
DEMO_DROP_POINTS = {1: (100, 200), 2: (300, 400)}  # 只有 2 个盒
```
**冒烟通过 ≠ 真链路通过。** 给补齐方案（扩到 6 盒 / 或明确标注"仅 2 盒冒烟用"）。

---

## 验收

```
## ① E-15 方案（合并 or 防错）+ 实施步骤
## ② E-16 处置
## ③ E-14 真实报错栈 + 根因 + 修正
## ④ notify_scheduler 的调度器读配置时机（文件:行号）+ 修改后的函数原文
## ⑤ V-11 补齐方案
## 每项的验收判据
```

## 红线

- ❌ **不动 `deploy/sorting_config.ini` 与 `deployment/sorting_config.ini` 的实际内容**
  —— 给方案，改文件要等用户确认（有两份，改错就出事）
- ❌ 不上电
- ❌ 不碰固件（P1/P2/P7）、不碰协议（P3/P8）、不碰视觉（P6）
