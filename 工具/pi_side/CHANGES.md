# pi_onkey.py 改动清单 (2026-09-23)

## 改动概览

实现5处必要改动，使一键启动服务符合赛规要求（R-R01/R-R02）：

1. ✅ 起链改走 p_go8.sh（含 HOME→PARK +145mm 避障）
2. ✅ RUNNING 判据改用 pgrep（防止脚本先退出误判）
3. ✅ 补"释放沿=停止"（RUNNING 下松开按钮 → pkill）
4. ✅ 补"同上电只允许跑一轮"拦截（读 TICK_MS + 检查日志）
5. ✅ BUTTON_PIN 由 23 改成 16（GPIO23 被 gpio-ir 占用）

---

## 详细改动

### 1. BUTTON_PIN 改为 16 (GPIO16 物理针36)
**文件**: pi_onkey.py  
**位置**: 第 97 行  
**原文**: `BUTTON_PIN = 23         # 物理针 16`  
**改为**: `BUTTON_PIN = 16         # 物理针 36（GPIO23/22 被 gpio-ir overlay 占用）`

**原因**: GPIO23/22 被 `/boot/config.txt` 的 `gpio-ir` / `gpio-ir-tx` overlay 占用，实测 GPIO16 空闲。  
**接线**: NO 黑线一根 → 物理针36=GPIO16；另一根 → 物理针9=GND

---

### 2. 新增配置常量
**文件**: pi_onkey.py  
**位置**: 第 101-109 行（新增）

```python
# 停止控制
STOP_ON_RELEASE = True  # RUNNING 下释放沿 → 停止链（默认开启）

# 同上电多轮拦截
ALLOW_SAME_BOOT = False  # True = 允许同一次上电跑多轮（默认禁止）
```

**新增**: 第 119-122 行
```python
# 同上电多轮拦截：日志路径模式
ROUND_LOG_PATTERN = "/home/pi/logs/round-R8-*.log"
BOARD_BOOT_GRACE_S = 5  # 板子开机后 5 秒内的日志不算"已跑过"
```

---

### 3. 起链改走 p_go8.sh
**文件**: pi_onkey.py  
**位置**: 第 106 行  
**原文**: `CHAIN_SCRIPT = "/home/pi/电控/deploy/run_chain.py"`  
**改为**: `CHAIN_SCRIPT = "/home/pi/p_go8.sh"`

**位置**: start_chain() 方法（第 289-403 行）  
**关键改动**:
- **命令**: 由 `["python3", CHAIN_SCRIPT, "--port", ...]` 改为 `["bash", CHAIN_SCRIPT]`
- **工作目录**: 由 `cwd="/home/pi/电控"` 改为 `cwd="/home/pi"`
- **日志命名**: 由 `round-{round_id}.log` 改为 `onkey-{timestamp}.log`（避免与 p_go8.sh 的日志冲突）

**前置检查新增**:
1. `is_chain_running()` 检查链是否已在跑（pgrep）→ 拒绝启动第二条链
2. `check_same_boot_block()` 同上电多轮拦截 → 拒绝同上电第二轮

**证据**: test_02 断言 `cmd = ["bash", "/home/pi/p_go8.sh"]` 且 stdin 精确写 `"HOME\n"` ✅

---

### 4. RUNNING 判据改用 pgrep
**文件**: pi_onkey.py  
**位置**: 第 290-301 行（新增方法）

```python
def is_chain_running(self) -> bool:
    """检查链是否正在运行（用 pgrep，不依赖 self.chain_process）。"""
    try:
        result = self.subprocess_runner.run(
            ["pgrep", "-f", "[r]un_chain.py"],
            capture_output=True,
            text=True,
        )
        # pgrep 找到进程 → 退出码 0；未找到 → 退出码 1
        return result.returncode == 0
    except Exception as exc:
        self.logger.warning(f"pgrep 检查失败：{exc}")
        return False
```

**位置**: wait_chain() 方法（第 405-416 行，完全重写）  
**原文**: 用 `self.chain_process.poll()` 等待退出码  
**改为**: 用 `is_chain_running()` 非阻塞轮询（每秒检查）

**原因**: p_go8.sh 内部 `nohup python3 ... &` + `sleep 30`，脚本先退出而链还在跑 → 用 `poll()` 会误判并可能起第二条链抢串口。

**证据**: test_08 验证"链已在跑 → start_chain() 拒绝且 Popen 未调用" ✅

---

### 5. 补"释放沿=停止"
**文件**: pi_onkey.py  
**位置**: 第 418-428 行（新增方法）

```python
def stop_chain(self) -> None:
    """停止链（pkill，不动板子状态）。"""
    self.logger.info("停止链：pkill -f [r]un_chain.py")
    try:
        self.subprocess_runner.run(
            ["pkill", "-f", "[r]un_chain.py"],
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        self.logger.warning(f"pkill 失败：{exc}")
```

**位置**: run() 主循环（第 467-481 行，RUNNING 分支重写）  
**关键逻辑**:
```python
# RUNNING：等待链退出 + 监听 release 沿（停止）
elif self.state == State.RUNNING:
    # 检查 release 沿（停止）
    if STOP_ON_RELEASE:
        event = self.poll_button()
        if event == "release":
            self.logger.info("按钮松开 → 停止链")
            self.stop_chain()
            self.state = State.STANDBY  # 回 STANDBY（不是 FAULT）
            self.chain_process = None
            self.logger.info("链已停止 → STANDBY")
            continue
```

**证据**: test_10 验证"RUNNING 下释放沿 → pkill 真被调用 + 状态回 STANDBY" ✅

---

### 6. 补"同上电只允许跑一轮"拦截
**文件**: pi_onkey.py  
**位置**: 第 303-345 行（新增方法）

```python
def get_board_boot_time(self) -> Optional[float]:
    """读取板子开机时刻（Unix 时间戳，秒）。失败返回 None。"""
    # ssh pi@172.20.10.8 "python3 /home/pi/pi_status_once.py"
    # 解析 TICK_MS=<毫秒> → 开机时刻 = 当前时间 - tick_ms

def check_same_boot_block(self) -> bool:
    """检查同上电多轮拦截。True = 拦截（拒绝启动），False = 放行。"""
    if os.environ.get("ALLOW_SAME_BOOT") == "1":
        return False  # 跳过拦截
    
    boot_time = self.get_board_boot_time()
    if boot_time is None:
        return False  # 无法获取，放行（记录警告）
    
    # 检查 /home/pi/logs/round-R8-*.log
    log_files = glob.glob(ROUND_LOG_PATTERN)
    for log_path in log_files:
        mtime = os.path.getmtime(log_path)
        if mtime > boot_time + BOARD_BOOT_GRACE_S:
            # 日志晚于开机时刻 + 5s → 拦截
            self.logger.error(">>> 必须「推到底 + 断电上电」后才能起下一轮")
            return True
    return False
```

**调用位置**: start_chain() 方法第 369-371 行  
```python
# 前置检查 2：同上电多轮拦截
if self.check_same_boot_block():
    return False
```

**证据**: test_09 验证"同上电第二轮 → 拒绝且 Popen 未被调用" ✅

---

## 测试结果

**命令**: `py -3 test_pi_onkey.py`  
**结果**: 12/12 全绿 ✅

**覆盖清单**:
- H-1 ✅ 全部测试通过
- H-2 ✅ test_02: cmd = ["bash", "/home/pi/p_go8.sh"] + stdin 精确写 "HOME\n"
- H-3 ✅ test_10: 释放沿 → pkill 真被调用 + 状态回 STANDBY
- H-4 ✅ test_08: 链已在跑 → start_chain() 拒绝且 Popen 未调用
- H-5 ✅ test_09: 同上电第二轮 → 拒绝且 Popen 未调用

---

## 部署步骤（需用户批准）

**前提**: 树莓派 pi@172.20.10.8 在线，免密 ssh 已配置

### 步骤 1: 上传文件
```bash
scp 工具/pi_side/pi_onkey.py pi@172.20.10.8:/home/pi/
scp 工具/pi_side/pi-onkey.service pi@172.20.10.8:/home/pi/
```

### 步骤 2: 安装 systemd 服务
```bash
ssh pi@172.20.10.8 << 'EOF'
sudo cp /home/pi/pi-onkey.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pi-onkey.service
sudo systemctl start pi-onkey.service
sudo systemctl status pi-onkey.service
EOF
```

### 步骤 3: 验证服务状态
```bash
ssh pi@172.20.10.8 "systemctl status pi-onkey.service"
ssh pi@172.20.10.8 "journalctl -u pi-onkey.service -n 50 --no-pager"
```

---

## 实机验收（用户在场）

### 验收 1: 按一下起链
**操作**: 按下按钮一次  
**预期**:
- 日志 `/home/pi/logs/onkey-<timestamp>.log` 出现 p_go8.sh 输出
- 包含 "HOME→PARK（+145.0mm / 11600 步）"
- 包含 "STEP_RESULT=1"（送到停靠位成功）
- 链开始运行（pgrep 能找到 run_chain.py）

### 验收 2: 跑轮中途按弹起停止
**操作**: 链运行中，按钮松开（弹起）  
**预期**:
- 链被 pkill 停止（pgrep 找不到 run_chain.py）
- 板子状态未变（不发任何运动/复位命令）
- 服务回 STANDBY 状态
- 再次按下按钮 → 拒绝启动（"链已在运行"或"同上电拦截"）

### 验收 3: 一轮结束后再按
**操作**: 一轮正常结束后，再次按下按钮  
**预期**:
- 被"同上电多轮拦截"挡住
- 日志提示 ">>> 必须「推到底 + 断电上电」后才能起下一轮"
- Popen 未被调用（链未起动）

### 验收 4: 断电上电后可再起
**操作**: X/Y 推到底 + 板子断电上电 + 按下按钮  
**预期**:
- 同上电拦截放行（板子 TICK_MS 小，日志 mtime 晚于开机时刻）
- 链正常起动

---

## 回滚方案（若验收失败）

```bash
ssh pi@172.20.10.8 << 'EOF'
sudo systemctl stop pi-onkey.service
sudo systemctl disable pi-onkey.service
sudo rm /etc/systemd/system/pi-onkey.service
sudo systemctl daemon-reload
EOF
```

---

## 证据汇总

| 改动点 | 文件:行号 | 原文前20字 | 验证方式 |
|--------|-----------|------------|----------|
| ① BUTTON_PIN=16 | pi_onkey.py:97 | `BUTTON_PIN = 23` | test_11 ✅ |
| ② 起链走 p_go8.sh | pi_onkey.py:106 | `CHAIN_SCRIPT = "/home/pi/电控/deploy/run_chain.py"` | test_02 ✅ |
| ③ cmd = ["bash", ...] | pi_onkey.py:387 | `cmd = ["bash", CHAIN_SCRIPT]` | test_02 ✅ |
| ④ pgrep 检查 | pi_onkey.py:290-301 | `def is_chain_running` | test_08 ✅ |
| ⑤ 释放沿停止 | pi_onkey.py:418-428 | `def stop_chain` | test_10 ✅ |
| ⑥ 同上电拦截 | pi_onkey.py:347-371 | `def check_same_boot_block` | test_09 ✅ |

---

## 未能核实项（Pi 离线）

1. **TICK_MS 格式**: 推断为 `TICK_MS=<毫秒>`（基于任务描述 "ssh pi@172.20.10.8 'python3 /home/pi/pi_status_once.py'"）
2. **round-R8-*.log 实际路径**: 推断为 `/home/pi/logs/round-R8-*.log`（基于 p_go8.sh:85）
3. **GPIO16 空闲状态**: 任务描述已确认"GPIO16 = 物理针36 实测空闲"

---

## 可证伪预测

1. **执行 start_chain() 且链已在跑** → `is_chain_running()` 返回 True → Popen 未被调用 → 函数返回 False
2. **执行 start_chain() 且同上电有旧日志** → `check_same_boot_block()` 返回 True → 函数返回 False
3. **RUNNING 状态下按钮松开** → `stop_chain()` 被调用 → `pkill -f [r]un_chain.py` 执行 → 状态回 STANDBY
4. **部署后按下按钮** → p_go8.sh 启动 → 日志包含 "HOME→PARK" + "STEP_RESULT=1" → run_chain.py 开始运行

---

**改动完成时间**: 2026-09-23  
**测试状态**: 12/12 全绿 ✅  
**部署状态**: 待用户批准
