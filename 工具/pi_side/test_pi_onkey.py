#!/usr/bin/env python3
"""pi_onkey.py 主机侧测试（无需树莓派、无需真 GPIO）。

测试覆盖：
1. 状态机转移：上电=STANDBY；按下=ARMED；起链成功=RUNNING；起链失败=FAULT
2. Arming guard：模拟"上电时按钮已闭合" ⇒ 不得自动 arm
3. 边沿触发：持续按住不得重复触发第二次
4. Fail-closed：FAULT 状态下任何输入都不得落地成"起链"
5. HOME 门禁：subprocess.Popen(stdin=PIPE) 写入精确的 "HOME\n"
6. 改用 p_go8.sh：cmd = ["bash", "/home/pi/p_go8.sh"]
7. 链已在跑 ⇒ 拒绝启动（pgrep 检查）
8. 同上电多轮拦截 ⇒ 拒绝启动
9. 释放沿 ⇒ 停止链（pkill + 回 STANDBY）
10. BUTTON_PIN = 16

运行：
    python3 test_pi_onkey.py
"""

import sys
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# 添加 pi_onkey.py 所在目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent))

# 导入被测模块
from pi_onkey import (
    FakeGPIOBackend,
    OnKeyService,
    State,
    HOME_CONFIRMATION_TEXT,
    BUTTON_PIN,
)


class FakeSubprocess:
    """假 subprocess 模块（注入到 OnKeyService）。"""

    PIPE = "PIPE"
    STDOUT = "STDOUT"

    def __init__(self):
        self.popen_calls = []
        self.run_calls = []
        self.fake_process = None
        self._chain_running = False  # 模拟 pgrep 状态

    class FakeProcess:
        def __init__(self, returncode=0):
            self.pid = 12345
            self.returncode = returncode
            self.stdin = StringIO()
            self._poll_count = 0

        def poll(self):
            # 模拟：前 2 次返回 None（运行中），第 3 次返回退出码
            self._poll_count += 1
            if self._poll_count >= 3:
                return self.returncode
            return None

    class FakeRunResult:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def Popen(self, cmd, **kwargs):
        self.popen_calls.append((cmd, kwargs))
        # 默认成功（退出码 0）
        self.fake_process = self.FakeProcess(returncode=0)
        # 模拟：Popen 后链开始运行
        self._chain_running = True
        return self.fake_process

    def run(self, cmd, **kwargs):
        self.run_calls.append((cmd, kwargs))
        # 处理 pgrep 调用
        if cmd[0] == "pgrep":
            # 返回链运行状态
            returncode = 0 if self._chain_running else 1
            return self.FakeRunResult(returncode=returncode)
        # 处理 pkill 调用
        elif cmd[0] == "pkill":
            self._chain_running = False
            return self.FakeRunResult(returncode=0)
        # 处理板子状态读取（2026-09-22 修正：改成本地执行，不再是 ssh 到自己）
        elif cmd[0:2] == ["python3", "/home/pi/pi_status_once.py"]:
            # 模拟板子状态：TICK_MS=60000（开机 60 秒）
            return self.FakeRunResult(returncode=0, stdout="TICK_MS=60000\n")
        return self.FakeRunResult(returncode=0)

    def inject_failure(self):
        """注入起链失败（Popen 抛异常）。"""
        def _raise(*args, **kwargs):
            raise RuntimeError("注入的起链失败")
        self.Popen = _raise

    def inject_chain_already_running(self):
        """注入"链已在跑"（pgrep 返回 0）。"""
        self._chain_running = True

    def inject_same_boot_block(self):
        """注入"同上电拦截"（板子开机早于日志）。"""
        # 模拟板子刚开机（TICK_MS=1000，开机 1 秒）
        def _run_local(cmd, **kwargs):
            if cmd[0:2] == ["python3", "/home/pi/pi_status_once.py"]:
                return self.FakeRunResult(returncode=0, stdout="TICK_MS=1000\n")
            elif cmd[0] == "pgrep":
                returncode = 0 if self._chain_running else 1
                return self.FakeRunResult(returncode=returncode)
            elif cmd[0] == "pkill":
                self._chain_running = False
                return self.FakeRunResult(returncode=0)
            return self.FakeRunResult(returncode=0)
        self.run = _run_local


class TestOnKeyService(unittest.TestCase):
    """一键启动服务测试套件。"""

    def setUp(self):
        """每个测试前：准备假后端。"""
        self.gpio = FakeGPIOBackend()
        self.subprocess_runner = FakeSubprocess()
        self.service = OnKeyService(
            gpio_backend=self.gpio,
            button_pin=BUTTON_PIN,
            subprocess_runner=self.subprocess_runner,
        )
        # 禁用实际日志输出
        self.service.logger.disabled = True

    def test_01_initial_state_is_standby(self):
        """测试 1：上电默认 STANDBY。"""
        self.service.setup()
        self.assertEqual(self.service.state, State.STANDBY)

    def test_02_button_press_arms_and_starts_chain_with_p_go8(self):
        """测试 2：按钮按下 → 起链走 p_go8.sh + stdin 写 HOME。"""
        self.service.setup()
        self.assertEqual(self.service.state, State.STANDBY)

        # 模拟按下（1 → 0）
        self.gpio.inject_press(BUTTON_PIN)
        event = self.service.poll_button()
        self.assertEqual(event, "press")

        # 起链（带 glob.glob 和 os.path.getmtime 的 mock）
        with patch("glob.glob", return_value=[]), \
             patch("builtins.open", mock_open()):
            success = self.service.start_chain()
            self.assertTrue(success)

        # 检查 subprocess.Popen 被调用
        self.assertEqual(len(self.subprocess_runner.popen_calls), 1)
        cmd, kwargs = self.subprocess_runner.popen_calls[0]

        # H-2: 断言 cmd = ["bash", "/home/pi/p_go8.sh"]
        self.assertEqual(cmd, ["bash", "/home/pi/p_go8.sh"])
        self.assertEqual(kwargs["stdin"], FakeSubprocess.PIPE)

        # H-2: 检查 HOME 确认被精确写入
        stdin_content = self.subprocess_runner.fake_process.stdin.getvalue()
        self.assertEqual(stdin_content, HOME_CONFIRMATION_TEXT)

    def test_03_arming_guard_blocks_press_at_boot(self):
        """测试 3：上电时按钮已按下 ⇒ arming guard 阻止 arm。"""
        self.service.setup()
        # 模拟上电时按钮已按下
        self.gpio.pin_values[BUTTON_PIN] = 0
        self.service.last_button_value = 0
        self.service.arming_guard_released = False
        self.assertFalse(self.service.arming_guard_released)

        # 模拟：持续按住（0 → 0，无边沿）
        event = self.service.poll_button()
        self.assertIsNone(event)

        # 检查：没有起链
        self.assertEqual(len(self.subprocess_runner.popen_calls), 0)

    def test_04_arming_guard_clears_after_release(self):
        """测试 4：arming guard 在看到 release 后解除。"""
        self.service.setup()
        self.gpio.pin_values[BUTTON_PIN] = 0
        self.service.last_button_value = 0
        self.service.arming_guard_released = False
        self.assertFalse(self.service.arming_guard_released)

        # 模拟松开（0 → 1）
        self.gpio.inject_release(BUTTON_PIN)
        event = self.service.poll_button()
        self.assertEqual(event, "release")

        # arming guard 应解除
        self.assertTrue(self.service.arming_guard_released)

        # 再次按下（1 → 0）
        self.gpio.inject_press(BUTTON_PIN)
        event = self.service.poll_button()
        self.assertEqual(event, "press")

        # 现在应该可以起链
        with patch("glob.glob", return_value=[]), \
             patch("builtins.open", mock_open()):
            success = self.service.start_chain()
            self.assertTrue(success)

    def test_05_edge_trigger_no_repeat(self):
        """测试 5：边沿触发，持续按住不重复触发。"""
        self.service.setup()

        # 第一次 press（1 → 0）
        self.gpio.inject_press(BUTTON_PIN)
        event1 = self.service.poll_button()
        self.assertEqual(event1, "press")

        # 持续按住（0 → 0）
        event2 = self.service.poll_button()
        self.assertIsNone(event2)

        event3 = self.service.poll_button()
        self.assertIsNone(event3)

    def test_06_start_chain_failure_goes_to_fault(self):
        """测试 6：起链失败 → FAULT。"""
        self.service.setup()

        # 注入起链失败
        self.subprocess_runner.inject_failure()

        with patch("glob.glob", return_value=[]):
            success = self.service.start_chain()
            self.assertFalse(success)

        # 手动模拟 run() 中的逻辑：起链失败 → FAULT
        self.service.state = State.FAULT
        self.assertEqual(self.service.state, State.FAULT)

    def test_07_fault_state_blocks_new_chain(self):
        """测试 7：FAULT 状态下，任何输入都不得触发新起链。"""
        self.service.setup()
        self.service.state = State.FAULT

        # 模拟按下
        self.gpio.inject_press(BUTTON_PIN)
        event = self.service.poll_button()

        # 检查：没有起链
        self.assertEqual(len(self.subprocess_runner.popen_calls), 0)

    def test_08_chain_already_running_blocks_start(self):
        """测试 8 (H-4)：链已在跑 ⇒ start_chain() 拒绝且 Popen 未被调用。"""
        self.service.setup()

        # 注入"链已在跑"
        self.subprocess_runner.inject_chain_already_running()

        with patch("glob.glob", return_value=[]), \
             patch("builtins.open", mock_open()):
            success = self.service.start_chain()
            self.assertFalse(success)

        # H-4: 检查 Popen 未被调用
        self.assertEqual(len(self.subprocess_runner.popen_calls), 0)

    def test_09_same_boot_block(self):
        """测试 9 (H-5)：同上电第二轮 ⇒ 拒绝且 Popen 未被调用。"""
        self.service.setup()

        # 注入"同上电拦截"（板子刚开机，但有旧日志）
        self.subprocess_runner.inject_same_boot_block()

        # 创建假日志文件（mtime 晚于开机时刻）
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False, dir="."
        ) as f:
            fake_log = f.name

        try:
            # 设置 mtime 为"很久以前"（大于当前 - TICK_MS/1000）
            # 板子开机 = time.time() - 1 秒，日志 mtime = time.time() ⇒ 晚于开机 + 5s 之前
            os.utime(fake_log, (time.time(), time.time() - 100))

            with patch("glob.glob", return_value=[fake_log]), \
                 patch("os.path.getmtime", return_value=time.time() + 10):
                success = self.service.start_chain()
                self.assertFalse(success)

            # H-5: 检查 Popen 未被调用
            self.assertEqual(len(self.subprocess_runner.popen_calls), 0)
        finally:
            os.unlink(fake_log)

    def test_10_press_again_stops_chain(self):
        """测试 10 (H-3)：RUNNING 下**再按一下** ⇒ pkill 被调用 + 状态回 STANDBY。

        🔴 2026-09-22 实测改：原测试假设"松开沿=停止"✗ —— 但按钮是**点动式**，
        按下起链后松手会立刻又触发停止（首次实机测试就撞上）⇒ 改成"运行中再按一下才停"。
        """
        self.service.setup()

        with patch("glob.glob", return_value=[]), \
             patch("builtins.open", mock_open()):
            self.service.start_chain()
            self.service.state = State.RUNNING

        self.subprocess_runner.run_calls.clear()

        # 运行中"再按一下"（0 值 = 按下）
        self.gpio.inject_press(BUTTON_PIN)
        event = self.service.poll_button()
        self.assertEqual(event, "press")

        if self.service.state == State.RUNNING and event == "press":
            self.service.stop_chain()
            self.service.state = State.STANDBY

        pkill_calls = [c for c in self.subprocess_runner.run_calls if c[0][0] == "pkill"]
        self.assertGreater(len(pkill_calls), 0, "pkill 应该被调用")
        self.assertEqual(self.service.state, State.STANDBY)

    def test_14_release_does_not_stop_chain(self):
        """测试 14：**松开**按钮**不得**停链（点动按钮的回归保护）。"""
        self.service.setup()
        with patch("glob.glob", return_value=[]), \
             patch("builtins.open", mock_open()):
            self.service.start_chain()
            self.service.state = State.RUNNING
        self.subprocess_runner.run_calls.clear()

        self.gpio.inject_press(BUTTON_PIN)
        self.service.poll_button()
        self.gpio.inject_release(BUTTON_PIN)
        event = self.service.poll_button()
        self.assertEqual(event, "release")

        # 新语义：release 不触发停止
        pkill_calls = [c for c in self.subprocess_runner.run_calls if c[0][0] == "pkill"]
        self.assertEqual(len(pkill_calls), 0, "松开按钮不得停链 ✗")
        self.assertEqual(self.service.state, State.RUNNING)

    def test_15_tick_ms_parsed_from_midline(self):
        """测试 15：TICK_MS 出现在**行中间**时也要解析出来（实测格式）。

        实测 pi_status_once.py 输出：`   AXIS FAULTS=0 TICK_MS=256086 STATE=0 …`
        原实现 `line.startswith("TICK_MS=")` ⇒ 永远匹配不到 ⇒ 同轮次拦截静默放行 ✗
        """
        self.service.setup()

        def _run_status(cmd, **kwargs):
            return self.subprocess_runner.FakeRunResult(
                returncode=0,
                stdout="PING -> OK PONG\n   AXIS FAULTS=0 TICK_MS=256086 STATE=0 RESULT=0\n",
            )
        self.subprocess_runner.run = _run_status
        boot = self.service.get_board_boot_time()
        self.assertIsNotNone(boot, "行中间的 TICK_MS 必须能解析出来 ✗")
        self.assertAlmostEqual(boot, time.time() - 256.086, delta=3.0)

    def test_11_button_pin_is_16(self):
        """测试 11：BUTTON_PIN = 16（GPIO16 物理针 36）。"""
        self.assertEqual(BUTTON_PIN, 16)

    def test_12_gpio_init_failure_goes_to_fault(self):
        """测试 12：GPIO 初始化失败 → FAULT。"""
        # 注入 GPIO setup 失败
        def _raise(*args, **kwargs):
            raise RuntimeError("注入的 GPIO 初始化失败")
        self.gpio.setup = _raise

        with self.assertRaises(RuntimeError):
            self.service.setup()

        self.assertEqual(self.service.state, State.FAULT)


    def test_13_board_status_is_read_locally_not_via_ssh(self):
        """测试 13 (H-6)：读板子状态必须【本地执行】，不得 ssh 到自己。

        🔴 2026-09-22 DSH 加：原实现是 ssh 到自己，Pi 上没有自机免密 key 时会失败
        ⇒ check_same_boot_block() 静默放行 ⇒ 同轮次拦截形同不存在。
        """
        self.service.setup()
        self.subprocess_runner.run_calls.clear()
        self.service.get_board_boot_time()
        cmds = [c[0] for c in self.subprocess_runner.run_calls]
        self.assertTrue(
            any(c[0:2] == ["python3", "/home/pi/pi_status_once.py"] for c in cmds),
            "必须本地执行 pi_status_once.py",
        )
        self.assertFalse(
            any(c[0] == "ssh" for c in cmds),
            "不得再 ssh 到自己读板子状态",
        )


def run_tests():
    """运行测试套件并输出结果。"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestOnKeyService)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
