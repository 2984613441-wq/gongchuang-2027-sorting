#!/usr/bin/env python3
"""气动夹爪测试脚本 - 树莓派侧

功能：
1. 通过串口发送命令给STM32，控制气动夹爪
2. 测试脉宽范围（1000us - 2000us）
3. 验证气动阀响应

使用方法：
    python test_pneumatic_gripper.py

前提条件：
1. STM32已烧录包含ec_pneumatic_gripper模块的固件
2. 树莓派与STM32串口连接正常（USART2，115200 8N1）
3. 气动阀已正确接线到PB11
"""

import serial
import time
import sys

# 串口配置
SERIAL_PORT = '/dev/ttyUSB0'  # 或 /dev/ttyACM0 或 /dev/serial0
BAUD_RATE = 115200
TIMEOUT = 1.0

# 测试脉宽（微秒）
PULSE_OPEN = 1000    # 张开
PULSE_CLOSE = 2000   # 闭合
PULSE_NEUTRAL = 1500 # 中位

def send_command(ser, cmd):
    """发送ASCII命令给STM32（如果支持诊断命令）"""
    ser.write((cmd + '\n').encode('utf-8'))
    time.sleep(0.1)
    response = ser.read_all().decode('utf-8', errors='ignore')
    return response

def test_pneumatic_basic(ser):
    """基本测试：张开-闭合-中位"""
    print("\n=== 基本功能测试 ===")

    tests = [
        ("张开", PULSE_OPEN),
        ("闭合", PULSE_CLOSE),
        ("中位", PULSE_NEUTRAL),
    ]

    for name, pulse in tests:
        print(f"\n[{name}] 设置脉宽 {pulse}us...")
        cmd = f"GRIP_PULSE {pulse}"
        resp = send_command(ser, cmd)
        print(f"响应: {resp}")

        print("观察气动阀是否动作（应能听到阀体切换声音）")
        print("观察夹爪是否响应...")
        input("按回车继续下一步...")

def test_pneumatic_sweep(ser):
    """扫频测试：1000us → 2000us 渐变"""
    print("\n=== 脉宽扫频测试 ===")
    print("从1000us到2000us，每次增加100us")

    for pulse in range(1000, 2100, 100):
        print(f"\n脉宽: {pulse}us")
        cmd = f"GRIP_PULSE {pulse}"
        resp = send_command(ser, cmd)
        print(f"响应: {resp}")
        time.sleep(1.0)

    print("\n扫频完成")

def test_pneumatic_cycle(ser, cycles=5):
    """循环测试：张开-闭合 N次"""
    print(f"\n=== 循环测试（{cycles}次）===")

    for i in range(cycles):
        print(f"\n第 {i+1}/{cycles} 次")

        # 张开
        print("  → 张开")
        send_command(ser, f"GRIP_PULSE {PULSE_OPEN}")
        time.sleep(1.0)

        # 闭合
        print("  → 闭合")
        send_command(ser, f"GRIP_PULSE {PULSE_CLOSE}")
        time.sleep(1.0)

    print("\n循环完成")

def test_with_binary_protocol(ser):
    """使用二进制协议测试（如果已实现）"""
    print("\n⚠️ 二进制协议测试暂未实现")
    print("请在固件中实现 PNEUMATIC_GRIPPER_CMD 命令字")

def main():
    print("=" * 50)
    print("气动夹爪测试程序")
    print("=" * 50)

    # 打开串口
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=TIMEOUT)
        print(f"✅ 串口已打开: {SERIAL_PORT} @ {BAUD_RATE}")
    except Exception as e:
        print(f"❌ 无法打开串口: {e}")
        print("\n可能的原因：")
        print("1. 串口设备名错误（尝试 ls /dev/tty*）")
        print("2. 权限不足（运行 sudo usermod -a -G dialout $USER）")
        print("3. 串口被其他程序占用")
        sys.exit(1)

    try:
        # 测试STM32连接
        print("\n测试STM32连接...")
        resp = send_command(ser, "PING")
        if "PONG" in resp or "OK" in resp:
            print(f"✅ STM32响应正常: {resp.strip()}")
        else:
            print(f"⚠️ STM32无响应或响应异常: {resp.strip()}")
            print("继续测试，但可能无法控制夹爪")

        # 菜单
        while True:
            print("\n" + "=" * 50)
            print("请选择测试项目：")
            print("1. 基本测试（张开-闭合-中位）")
            print("2. 扫频测试（1000-2000us渐变）")
            print("3. 循环测试（张开-闭合 N次）")
            print("4. 手动输入脉宽")
            print("5. 退出")
            print("=" * 50)

            choice = input("请输入选项（1-5）: ").strip()

            if choice == '1':
                test_pneumatic_basic(ser)
            elif choice == '2':
                test_pneumatic_sweep(ser)
            elif choice == '3':
                cycles = int(input("输入循环次数（默认5）: ") or "5")
                test_pneumatic_cycle(ser, cycles)
            elif choice == '4':
                pulse = int(input("输入脉宽（微秒，1000-2000）: "))
                cmd = f"GRIP_PULSE {pulse}"
                resp = send_command(ser, cmd)
                print(f"响应: {resp}")
            elif choice == '5':
                print("退出测试")
                break
            else:
                print("无效选项，请重新输入")

    except KeyboardInterrupt:
        print("\n\n测试中断")

    finally:
        # 关闭串口
        if ser.is_open:
            # 回到中位
            send_command(ser, f"GRIP_PULSE {PULSE_NEUTRAL}")
            ser.close()
            print("✅ 串口已关闭")

if __name__ == "__main__":
    main()
