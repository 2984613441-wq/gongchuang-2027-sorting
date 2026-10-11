# MaixCAM摄像头占用修复方案 — 2026-09-23

## 根因
`/maixapp/apps/launcher/launcher`（GUI程序，PID 863）占用摄像头，导致生产视觉程序初始化VI通道失败。

`/etc/init.d/S99vision` 的 `free_camera()` 只杀了 `launcher_daemon`（守护进程），但**遗漏了其子进程 `launcher`**（实际持有摄像头的GUI）。

---

## 修复方案（最小侵入）

### 步骤1：备份现有配置

```bash
ssh root@172.20.10.9 "cp /etc/init.d/S99vision /etc/init.d/S99vision.bak-20260923"
```

### 步骤2：修改S99vision的free_camera()

将 `launcher_daemon` 改为 `launcher`（不带_daemon后缀，匹配实际子进程名）：

**原代码（第9-15行）**：
```bash
free_camera() {
    for pat in maixvision_server launcher_daemon benchmark; do
        for p in $(ps | grep "$pat" | grep -v grep | awk '{print $1}'); do
            echo "[init] kill $pat pid=$p" >> "$BOOT"
            kill "$p" 2>/dev/null
        done
    done
}
```

**修改为**：
```bash
free_camera() {
    # 2026-09-23 修复：launcher（不是launcher_daemon）才是实际持有摄像头的GUI程序
    for pat in maixvision_server launcher benchmark; do
        for p in $(ps | grep "$pat" | grep -v grep | awk '{print $1}'); do
            echo "[init] kill $pat pid=$p" >> "$BOOT"
            kill "$p" 2>/dev/null
        done
    done
}
```

**关键变更**：`launcher_daemon` → `launcher`

---

### 步骤3：应用修改（远程执行）

```bash
# 在本机执行（Windows Git Bash）
ssh root@172.20.10.9 "sed -i.bak-daemon 's/launcher_daemon/launcher/g' /etc/init.d/S99vision"
```

### 步骤4：验证修改

```bash
ssh root@172.20.10.9 "grep 'for pat in' /etc/init.d/S99vision"
```

**期望输出**：
```
    for pat in maixvision_server launcher benchmark; do
```

### 步骤5：重启相机（物理断电上电）

```bash
# 1. 拔掉MaixCAM电源（Type-C线）
# 2. 等待5秒
# 3. 重新插入电源
# 4. 等待30秒启动
```

**为什么必须物理重启**：
- `launcher`（PID 863）已经持有VI设备文件描述符
- `/etc/init.d/S99vision restart` 只重启supervisor，不会杀已有的launcher
- 必须通过重启让修改后的 `free_camera()` 在开机时执行

---

## 验收判据（可执行）

### A1：开机自启动验收

**在树莓派上执行**：
```bash
python3 /home/pi/link_listen_8765.py --duration 60
```

**判据**：
- 30秒内收到第一批次
- 最大批次间隔 ≤ 2秒
- 无 "connection refused" 错误

**通过标准**：连续观察60秒，符合上述3条

### A2：崩溃恢复验收

**在相机上杀掉sender**：
```bash
ssh root@172.20.10.9 "ps | grep stage1_color_v6_send | grep -v grep | awk '{print \$1}' | xargs kill"
```

**判据**：
- 杀掉后10秒内在树莓派再次收到批次
- 负载（`uptime`）保持在 1.0 以下（不再累积到13+）

---

## 回滚方案

### 快速回滚（恢复到手动模式）

```bash
# 停止自启动
ssh root@172.20.10.9 "/etc/init.d/S99vision stop"

# 禁用开机自启动（重命名脚本）
ssh root@172.20.10.9 "mv /etc/init.d/S99vision /etc/init.d/S99vision.disabled"

# 恢复原文件（如果需要）
ssh root@172.20.10.9 "cp /etc/init.d/S99vision.bak-20260923 /etc/init.d/S99vision"
```

**此时状态**：回到"手动ssh进去跑sender"的原始模式

### 完全回滚清单

已创建的备份文件（按时间倒序）：
1. `/etc/init.d/S99vision.bak-daemon` — sed自动备份（本次修改前）
2. `/etc/init.d/S99vision.bak-20260923` — 手动备份（本次修改前）
3. `/maixapp/auto_start.txt.bak-*` — benchmark→none改动的备份
4. `/var/log/vision-boot.log` — 开机诊断日志（记录free_camera执行过程）

---

## 风险评估

### 低风险（可逆）

1. **修改init.d脚本**：
   - 已创建2份备份
   - 只改1行（launcher_daemon→launcher）
   - 随时可通过重命名禁用

2. **杀launcher进程**：
   - launcher是GUI程序，杀掉后不影响系统核心功能
   - maixvision_server仍运行（远程开发通道保留）
   - 重启即恢复

### 中等风险（需注意）

1. **误杀其他launcher进程**：
   - 当前进程表只有1个launcher（PID 863）
   - grep模式足够精确（`grep "$pat" | grep -v grep`）
   - 最坏情况：误杀后重启恢复

2. **负载回落需要时间**：
   - 死循环累积的load average需要5-15分钟自然衰减
   - 期间不影响功能，只是数字难看

### 零风险项

- ✅ 不修改固件
- ✅ 不修改GPIO映射
- ✅ 不修改通信协议
- ✅ 不修改视觉程序本体
- ✅ 不需要密码/敏感信息
- ✅ 重启即可恢复所有改动

---

## 可证伪预测

1. **修改后第一次重启**：
   - 预测：`/var/log/vision-boot.log` 会出现 `[init] kill launcher pid=XXX`
   - 证伪条件：如果没出现，说明launcher没被匹配到

2. **stage1启动**：
   - 预测：不再出现 `RuntimeError: mmf add vi channel failed`
   - 证伪条件：如果仍报错，说明还有其他进程占用（需进一步排查）

3. **负载回落**：
   - 预测：重启后30分钟内负载降到 <2.0
   - 证伪条件：如果仍然 >10，说明有其他进程死循环

---

## 补充：负载回落加速（可选）

如果验收通过但负载仍高（>5.0），可主动清理死循环进程：

```bash
# 查看高CPU进程
ssh root@172.20.10.9 "top -b -n 1 | head -20"

# 如果发现异常Python进程，记录PID后杀掉
ssh root@172.20.10.9 "kill <PID>"
```

**注意**：不要杀PID 605（正常的stage1），只杀CPU持续100%的异常进程。

---

## 执行清单（复制粘贴版）

```bash
# === 在本机Git Bash执行 ===

# 1. 备份
ssh root@172.20.10.9 "cp /etc/init.d/S99vision /etc/init.d/S99vision.bak-20260923"

# 2. 修改
ssh root@172.20.10.9 "sed -i.bak-daemon 's/launcher_daemon/launcher/g' /etc/init.d/S99vision"

# 3. 验证
ssh root@172.20.10.9 "grep 'for pat in' /etc/init.d/S99vision"
# 期望输出：for pat in maixvision_server launcher benchmark; do

# 4. 物理重启MaixCAM（拔电源，等5秒，插回，等30秒）

# 5. 验收（在树莓派上）
ssh pi@172.20.10.8 "python3 /home/pi/link_listen_8765.py --duration 60"

# 6. 检查负载
ssh root@172.20.10.9 "uptime"
```

---

**交付时间**：2026-09-23  
**验证状态**：待执行  
**回滚难度**：极低（3条命令）  
**风险等级**：Level 1（可逆，无硬件影响）
