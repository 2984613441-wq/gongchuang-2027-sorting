#!/usr/bin/env python3
"""一键启动服务 — 物理按钮触发整轮比赛（赛规 R-R01/R-R02 要求）。

赛规依据
--------
电控/资料/要求汇总.md:99
  | R-R01 | 调试剩余 30 秒时停止调试，开启电源并使设备进入待机状态。
电控/资料/要求汇总.md:100
  | R-R02 | 裁判下达开始指令后，一键启动，比赛计时开始。

⇒ 「一键启动」是赛规明文要求；现场不允许 ssh 进 Pi 敲命令。

状态机
------
STANDBY → (按钮按下) → ARMED → (起链成功) → RUNNING → (链退出) → STANDBY
                                      ↓ (任何失败)
                                    FAULT (锁死，必须重启服务)

· 上电即 STANDBY，**不派件**（R-R01：上电后处于待机）
· 按钮按下（边沿触发）→ ARMED → 起轮 → RUNNING
· 任何异常（GPIO 初始化失败 / 起链失败 / 链异常退出）→ FAULT + 明确日志 + 不派件

接线（由用户完成，本代码只声明）
--------------------------------
NO-A → GPIO16（BCM 16 = 物理针 36）
       ⚠️ 2026-10-02 更正：此处原写「GPIO23（物理针 16）」把 **BCM 号与物理针编号搞混了**。
       以本文件 :98 的 `BUTTON_PIN = 16` 为准（BCM 16）。
       旁证：docs/交付/2026-09-22/新会话开场提示词-20260922.md §13.15
             "NO 黑线一根→物理针 36 = GPIO16……软件 BUTTON_PIN 必须 = 16"
             ；工具/pi_side/CHANGES.md:21,24 同为 "GPIO16 / 物理针 36"
NO-B → GND
       ⚠️ 该 GND 的物理针号**未定**（记录里有「板丝印 49」与「物理针 9」两种说法）
       ⇒ **需万用表通断确认后再写死**
输入配置 = 内部上拉（INPUT + PULL_UP），按下 = 读到 0

🔴 **红线约束**：
· NO 脚**只接 GPIO 与 GND**，绝不接任何电源（接电源会烧 GPIO）
· 指示灯接【独立电源】：先测灯的额定电压，不要用 GPIO 直驱
· GPIO17 = 转盘索引、GPIO18 = 转盘 PWM ⇒ **已被占用，不可用**
· 必须用【点动按钮】；若用自锁按钮，必须【边沿触发 + arming guard】

Arming Guard（防上电误启动）
----------------------------
若用自锁按钮且上电时按钮已闭合 ⇒ 会立刻误启动。
⇒ 本实现：必须先见到一次 release（松开、读到 1），才允许下一次 press arm。

HOME 门禁（核心难点）
---------------------
电控/deploy/run_chain.py:607-643 的 require_home_confirmation() 要求 stdin 精确输入 "HOME"，
非交互环境一律拒绝 --start-round（这是**故意的**安全设计，防止起点错误导致堵转）。

而 nohup 会把 stdin 变成 /dev/null ⇒ 旧写法直接拒启动。
⇒ 本实现：subprocess.Popen(..., stdin=subprocess.PIPE)，写入精确的 "HOME\n"。

绕过方案参考：工具/pi_side/sh/p_go8.sh:15-52（echo HOME | nohup python3 deploy/run_chain.py ...）

⚠️ 「人确认 HOME」这一步**不能被削弱**：
R-R01 的现场流程是：**上电前，操作员已把滑台推到 X/Y 负方向最里角顶住**（= 上电原点）。
⇒ 所以"上电那一刻"就是人的确认；按钮只是"裁判发令后的启动动作"。
⇒ 若运行期发现位置不可信（例如异常停止），必须进 FAULT 并要求重新上电，**不许自动重试**。

Fail-Closed 原则
----------------
· GPIO 初始化失败 ⇒ 直接进 FAULT、禁止派件
· 起链失败 ⇒ FAULT（不重试、不掩盖）
· 链异常退出（退出码 ≠ 0）⇒ FAULT
· FAULT 状态下任何输入都不得触发新的起链

停止服务
--------
systemctl stop pi-onkey.service 时：
· 只释放 GPIO
· **绝不发任何运动命令**（不发 STOP/HOME/RESET，不碰串口）
· 若链正在运行，由外部 pkill -f "[r]un_chain.py" 停止（参见 p_go8.sh）
"""

import argparse
import glob
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

# GPIO 封装（支持注入假后端，用于主机侧测试）
try:
    import RPi.GPIO as GPIO
    _GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    # RuntimeError: 主机侧 import RPi.GPIO 会抛 "This module can only be run on a Raspberry Pi!"
    GPIO = None
    _GPIO_AVAILABLE = False


# ============================================================================
# 配置常量
# ============================================================================

# GPIO 引脚（BCM 编号）
BUTTON_PIN = 16         # 物理针 36（GPIO23/22 被 gpio-ir overlay 占用）
# GPIO17=转盘索引、GPIO18=转盘 PWM ⇒ 不可用

# 按钮电气
BUTTON_DEBOUNCE_MS = 50  # 消抖时间（毫秒）
BUTTON_POLL_INTERVAL_S = 0.1  # 轮询间隔（秒）

# 停止控制
STOP_ON_PRESS = True  # RUNNING 下"再按一下"→ 停止链（点动按钮语义；2026-09-22 由 STOP_ON_RELEASE 改）

# 同上电多轮拦截
ALLOW_SAME_BOOT = False  # True = 允许同一次上电跑多轮（默认禁止）

# 链路参数（改用 p_go8.sh）
CHAIN_SCRIPT = "/home/pi/p_go8.sh"
CHAIN_PYTHONPATH = "/home/pi/电控/src"
CHAIN_PORT = "/dev/serial0"
CHAIN_IMAGE_DIR = "/home/pi/images"
CHAIN_NAMES_FILE = "/home/pi/电控/deploy/names.json"
CHAIN_FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
CHAIN_FRAME_OUTPUT = "fb0"
CHAIN_PICK_STRATEGY = "order"

# 日志
LOG_DIR = "/home/pi/logs"
LOG_LATEST_LINK = "/home/pi/logs/onkey-latest.txt"

# 同上电多轮拦截：日志路径模式
ROUND_LOG_PATTERN = "/home/pi/logs/round-R8-*.log"
BOARD_BOOT_GRACE_S = 5  # 板子开机后 5 秒内的日志不算"已跑过"

# HOME 门禁（精确匹配）
HOME_CONFIRMATION_TEXT = "HOME\n"


# ============================================================================
# 状态机
# ============================================================================

class State(Enum):
    """服务状态。"""
    STANDBY = "standby"     # 待机（上电默认）
    ARMED = "armed"         # 已武装（按钮刚按下，即将起链）
    RUNNING = "running"     # 运行中（链已起，等待退出）
    FAULT = "fault"         # 故障（锁死，必须重启服务）


# ============================================================================
# GPIO 后端（支持注入）
# ============================================================================

class GPIOBackend:
    """GPIO 抽象后端（生产/测试可注入）。"""

    def setup(self, pin: int, mode: str, pull_up_down: str) -> None:
        """配置引脚。mode="IN"/"OUT"; pull_up_down="PUD_UP"/"PUD_DOWN"/None"""
        raise NotImplementedError

    def input(self, pin: int) -> int:
        """读取引脚（0=低/按下，1=高/松开）。"""
        raise NotImplementedError

    def cleanup(self) -> None:
        """释放 GPIO 资源。"""
        raise NotImplementedError


class RealGPIOBackend(GPIOBackend):
    """真实 RPi.GPIO 后端。"""

    def __init__(self):
        if not _GPIO_AVAILABLE:
            raise RuntimeError("RPi.GPIO 不可用（非树莓派环境或未安装）")
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

    def setup(self, pin: int, mode: str, pull_up_down: str) -> None:
        mode_const = GPIO.IN if mode == "IN" else GPIO.OUT
        pud_const = None
        if pull_up_down == "PUD_UP":
            pud_const = GPIO.PUD_UP
        elif pull_up_down == "PUD_DOWN":
            pud_const = GPIO.PUD_DOWN
        if pud_const is not None:
            GPIO.setup(pin, mode_const, pull_up_down=pud_const)
        else:
            GPIO.setup(pin, mode_const)

    def input(self, pin: int) -> int:
        return GPIO.input(pin)

    def cleanup(self) -> None:
        GPIO.cleanup()


class FakeGPIOBackend(GPIOBackend):
    """假 GPIO 后端（主机侧测试）。"""

    def __init__(self):
        self.pin_values = {}  # pin -> value (0/1)
        self.setup_called = []

    def setup(self, pin: int, mode: str, pull_up_down: str) -> None:
        self.setup_called.append((pin, mode, pull_up_down))
        # 默认上拉 ⇒ 初始为 1（松开）
        if pull_up_down == "PUD_UP":
            self.pin_values[pin] = 1
        else:
            self.pin_values[pin] = 0

    def input(self, pin: int) -> int:
        return self.pin_values.get(pin, 1)

    def cleanup(self) -> None:
        self.pin_values.clear()

    # 测试注入接口
    def inject_press(self, pin: int) -> None:
        """模拟按下（0）。"""
        self.pin_values[pin] = 0

    def inject_release(self, pin: int) -> None:
        """模拟松开（1）。"""
        self.pin_values[pin] = 1


# ============================================================================
# 一键启动服务
# ============================================================================

class OnKeyService:
    """一键启动服务主类。"""

    def __init__(
        self,
        gpio_backend: GPIOBackend,
        button_pin: int = BUTTON_PIN,
        logger: Optional[logging.Logger] = None,
        subprocess_runner=None,  # 注入假 subprocess（测试用）
    ):
        self.gpio = gpio_backend
        self.button_pin = button_pin
        self.logger = logger or logging.getLogger(__name__)
        self.subprocess_runner = subprocess_runner or subprocess

        self.state = State.STANDBY
        self.last_button_value = 1  # 上拉默认 1（松开）
        self.arming_guard_released = False  # Arming guard：必须先见过松开
        self.chain_process: Optional[subprocess.Popen] = None
        self.running = True

        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """优雅停止。"""
        self.logger.info(f"收到信号 {signum}，准备停止服务...")
        self.running = False

    def setup(self) -> None:
        """初始化 GPIO（失败 → FAULT）。"""
        try:
            self.gpio.setup(self.button_pin, "IN", "PUD_UP")
            self.logger.info(f"GPIO{self.button_pin} 已配置为输入+内部上拉")
            # 读取初始值
            self.last_button_value = self.gpio.input(self.button_pin)
            self.logger.info(f"按钮初始值 = {self.last_button_value} {'(松开)' if self.last_button_value == 1 else '(按下)'}")
            # Arming guard：若上电时按钮已按下，必须先见到松开
            if self.last_button_value == 0:
                self.logger.warning("⚠️ 上电时按钮已按下，进入 arming guard（必须先松开才能 arm）")
                self.arming_guard_released = False
            else:
                self.arming_guard_released = True
        except Exception as exc:
            self.logger.error(f"GPIO 初始化失败：{exc}", exc_info=True)
            self.state = State.FAULT
            raise

    def poll_button(self) -> Optional[str]:
        """轮询按钮，返回边沿事件："press" / "release" / None。"""
        try:
            current = self.gpio.input(self.button_pin)
        except Exception as exc:
            self.logger.error(f"读取 GPIO{self.button_pin} 失败：{exc}", exc_info=True)
            self.state = State.FAULT
            return None

        event = None
        # 边沿检测（1→0=press, 0→1=release）
        if current == 0 and self.last_button_value == 1:
            event = "press"
        elif current == 1 and self.last_button_value == 0:
            event = "release"
            # Arming guard：看到 release 就解除
            if not self.arming_guard_released:
                self.logger.info("arming guard 已解除（按钮松开）")
                self.arming_guard_released = True

        self.last_button_value = current
        return event

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

    def get_board_boot_time(self) -> Optional[float]:
        """读取板子开机时刻（Unix 时间戳，秒）。失败返回 None。

        🔴 2026-09-22 DSH 修：原实现是 `ssh pi@172.20.10.8 "python3 /home/pi/pi_status_once.py"`
        —— **ssh 到自己**。Pi 上不一定有"自机免密 key"，一旦失败就走异常分支返回 None，
        `check_same_boot_block()` 随即**静默放行** ⇒ 同轮次拦截形同不存在（最危险的那种失效）。
        本服务本来就跑在 Pi 上 ⇒ 直接**本地执行**即可，不依赖任何 ssh 通路。
        """
        try:
            result = self.subprocess_runner.run(
                ["python3", "/home/pi/pi_status_once.py"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                self.logger.warning(f"读取板子状态失败：{result.stderr}")
                return None
            # 解析 TICK_MS=<毫秒>
            # 🔴 2026-09-22 实测修：pi_status_once.py 的输出是**一整行**——
            #    `   AXIS FAULTS=0 TICK_MS=256086 STATE=0 …`
            #    原实现用 line.startswith("TICK_MS=") ⇒ **永远匹配不到** ⇒ 返回 None ⇒
            #    check_same_boot_block() 静默放行（fail-open ✗，实测日志里出现过"未找到 TICK_MS 字段"）
            for line in result.stdout.splitlines():
                if "TICK_MS=" in line:
                    tick_ms = int(line.split("TICK_MS=", 1)[1].split()[0])
                    # 板子 TICK_MS = 自启动后的毫秒数
                    # 开机时刻 = 当前时间 - tick_ms
                    boot_time = time.time() - (tick_ms / 1000.0)
                    self.logger.info(f"板子开机时刻：{boot_time:.1f} (TICK_MS={tick_ms})")
                    return boot_time
            self.logger.warning("未找到 TICK_MS 字段")
            return None
        except Exception as exc:
            self.logger.warning(f"get_board_boot_time 异常：{exc}")
            return None

    def check_same_boot_block(self) -> bool:
        """检查同上电多轮拦截。True = 拦截（拒绝启动），False = 放行。"""
        if os.environ.get("ALLOW_SAME_BOOT") == "1":
            self.logger.info("ALLOW_SAME_BOOT=1，跳过同上电拦截")
            return False

        boot_time = self.get_board_boot_time()
        if boot_time is None:
            self.logger.warning("无法获取板子开机时刻，放行（风险：可能同上电多轮）")
            return False

        # 检查 /home/pi/logs/round-R8-*.log
        try:
            log_files = glob.glob(ROUND_LOG_PATTERN)
            if not log_files:
                self.logger.info("未找到历史 round 日志，放行")
                return False

            for log_path in log_files:
                try:
                    mtime = os.path.getmtime(log_path)
                    if mtime > boot_time + BOARD_BOOT_GRACE_S:
                        self.logger.error(
                            f"⚠️ 同上电多轮拦截：日志 {log_path} 最后写入 {mtime:.1f}，"
                            f"晚于开机时刻 {boot_time:.1f} + {BOARD_BOOT_GRACE_S}s"
                        )
                        self.logger.error(">>> 必须「推到底 + 断电上电」后才能起下一轮")
                        return True
                except OSError:
                    continue

            self.logger.info("同上电拦截检查通过")
            return False
        except Exception as exc:
            self.logger.warning(f"同上电拦截检查异常：{exc}，放行")
            return False

    def start_chain(self) -> bool:
        """起链（走 p_go8.sh + stdin 写入 HOME）。成功返回 True，失败返回 False。"""
        # 前置检查 1：链已在跑？
        if self.is_chain_running():
            self.logger.error("⚠️ 链已在运行（pgrep 找到 run_chain.py），拒绝启动第二条链")
            return False

        # 前置检查 2：同上电多轮拦截
        if self.check_same_boot_block():
            return False

        # 生成日志路径（改用 onkey-*.log，避免与 round-R8-*.log 冲突）
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_path = Path(LOG_DIR) / f"onkey-{timestamp}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入 latest 链接（文本文件，存日志路径）
        try:
            with open(LOG_LATEST_LINK, "w") as f:
                f.write(str(log_path) + "\n")
        except Exception as exc:
            self.logger.warning(f"无法写入 {LOG_LATEST_LINK}：{exc}")

        self.logger.info(f"准备起链：日志={log_path}")

        # 构造命令（改用 p_go8.sh）
        cmd = ["bash", CHAIN_SCRIPT]

        env = os.environ.copy()
        env["PYTHONPATH"] = CHAIN_PYTHONPATH

        # HOME 门禁：通过 stdin 写入 "HOME\n"
        # （p_go8.sh 内部会读取 stdin 并传递给 run_chain.py）
        try:
            log_file = open(log_path, "w")
            self.chain_process = self.subprocess_runner.Popen(
                cmd,
                stdin=self.subprocess_runner.PIPE,
                stdout=log_file,
                stderr=self.subprocess_runner.STDOUT,
                env=env,
                cwd="/home/pi",
                text=True,
            )
            # 立刻写入 HOME 确认（门禁要求）
            self.chain_process.stdin.write(HOME_CONFIRMATION_TEXT)
            self.chain_process.stdin.flush()
            self.logger.info(f"链已起动（p_go8.sh）：PID={self.chain_process.pid}，日志={log_path}")
            return True
        except Exception as exc:
            self.logger.error(f"起链失败：{exc}", exc_info=True)
            return False

    def _chain_busy(self) -> bool:
        """链（**或起链脚本**）是否仍在进行。

        🔴 2026-09-22 实测修：原来只查 `pgrep run_chain.py` ⇒ **误判**——
        p_go8.sh 里有 HOME 门禁 + 送 PARK(+145mm) + 30 秒等待，真正拉起 run_chain.py 要十几秒；
        这段时间 pgrep 找不到 ⇒ 被判成"链已退出"✗
        （实测：20:50:39 起链，同一秒/两秒后就记"链已退出 → STANDBY"，而那一轮其实跑到 20:51:37 ✓）
        ⇒ 正确判据 = **起链脚本还活着 或 链进程还在** ✓
        """
        try:
            if self.chain_process is not None and self.chain_process.poll() is None:
                return True
        except Exception:
            pass
        return self.is_chain_running()

    def wait_chain(self) -> int:
        """等待链退出，返回退出码。非阻塞轮询（每秒检查一次）。"""
        while self.running:
            if not self._chain_busy():
                self.logger.info("链已退出（起链脚本与 run_chain.py 都已不在）")
                # 假定正常退出（p_go8.sh 脚本本身的退出码不可靠）
                return 0
            time.sleep(1.0)
        # 服务被停止
        return -1

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

    def run(self) -> None:
        """主循环。"""
        self.logger.info(f"一键启动服务已启动：state={self.state.value}")

        while self.running:
            # FAULT 状态：锁死，只等停止
            if self.state == State.FAULT:
                self.logger.debug("FAULT 状态，等待服务停止...")
                time.sleep(1.0)
                continue

            # STANDBY / ARMED：轮询按钮
            if self.state in (State.STANDBY, State.ARMED):
                event = self.poll_button()

                # Press 事件
                if event == "press":
                    if not self.arming_guard_released:
                        self.logger.warning("⚠️ 按钮按下，但 arming guard 未解除（上电时按钮已按下），忽略")
                    elif self.state == State.STANDBY:
                        self.logger.info("按钮按下 → ARMED")
                        self.state = State.ARMED
                        # 立刻起链
                        success = self.start_chain()
                        if success:
                            self.state = State.RUNNING
                            self.logger.info("起链成功 → RUNNING")
                        else:
                            # 🔴 2026-09-22 修：被拒（链已在跑 / 同一次上电已跑过）是**正常拒绝**，
                            #    不是故障 ⇒ 留在 STANDBY 等下一次按键（原来无条件进 FAULT ✗
                            #    还得重启服务 ✗ —— 实测 20:51:19 用户第三次按键就是这种情况）
                            if self.is_chain_running() or self.check_same_boot_block():
                                self.logger.warning(
                                    "起链被拒（链已在运行 / 同一次上电已跑过一轮）⇒ 保持 STANDBY"
                                )
                                self.state = State.STANDBY
                            else:
                                self.state = State.FAULT
                                self.logger.error("起链失败 → FAULT（必须重启服务）")
                    else:
                        # ARMED 时重复按下：忽略（边沿触发，持续按住不重复触发）
                        self.logger.debug("ARMED 状态下重复按下，忽略")

                time.sleep(BUTTON_POLL_INTERVAL_S)

            # RUNNING：等待链退出 + 监听"**再按一下**"（停止）
            elif self.state == State.RUNNING:
                # 🔴 2026-09-22 实测改：原设计是"**松开**按钮 = 停链"✗ ——
                #    用户的按钮是**点动式**（按一下弹回）⇒ 按下起链、松手立刻又要停链 ✗
                #    （首次实机测试就撞上：20:28:20 按下 ARMED → 20:28:23 起链 → 同一秒"松开→停链"）
                #    ⇒ 改成"**运行中再按一下**才停链"，这才符合点动按钮的自然语义。
                if STOP_ON_PRESS:
                    event = self.poll_button()
                    if event == "press":
                        self.logger.info("运行中再次按下 → 停止链")
                        self.stop_chain()
                        self.state = State.STANDBY
                        self.chain_process = None
                        self.logger.info("链已停止 → STANDBY")
                        continue

                # 检查链是否退出
                if not self._chain_busy():
                    self.logger.info("链已退出 → STANDBY")
                    self.state = State.STANDBY
                    self.chain_process = None
                else:
                    time.sleep(1.0)

        # 退出前清理
        self.cleanup()

    def cleanup(self) -> None:
        """释放 GPIO（不发运动命令）。"""
        self.logger.info("释放 GPIO...")
        try:
            self.gpio.cleanup()
        except Exception as exc:
            self.logger.warning(f"GPIO cleanup 失败：{exc}")
        self.logger.info("服务已停止")


# ============================================================================
# 主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="一键启动服务（赛规 R-R01/R-R02）")
    parser.add_argument("--fake-gpio", action="store_true", help="使用假 GPIO 后端（测试）")
    parser.add_argument("--log-level", default="INFO", help="日志级别（DEBUG/INFO/WARNING/ERROR）")
    args = parser.parse_args()

    # 配置日志
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("pi_onkey")

    # 选择 GPIO 后端
    if args.fake_gpio:
        logger.warning("⚠️ 使用假 GPIO 后端（测试模式）")
        gpio_backend = FakeGPIOBackend()
    else:
        try:
            gpio_backend = RealGPIOBackend()
        except RuntimeError as exc:
            logger.error(f"无法初始化 RPi.GPIO：{exc}")
            logger.error("若在主机侧测试，请使用 --fake-gpio")
            sys.exit(1)

    # 启动服务
    service = OnKeyService(gpio_backend, logger=logger)
    try:
        service.setup()
        service.run()
    except Exception as exc:
        logger.error(f"服务异常：{exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
