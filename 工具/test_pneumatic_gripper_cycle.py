#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
气动夹爪测试脚本 - 1秒吸附，1秒松开循环

测试逻辑：
1. 连接STM32串口
2. 循环发送 GRIP_CLOSE（吸附）和 GRIP_OPEN（松开）
3. 每个动作持续1秒

日期：2026-10-11
"""

import serial
import time
import sys

# 配置
SERIAL_PORT = 'COM3'  # 根据实际情况修改
BAUD_RATE = 115200
TIMEOUT = 1.0

# 命令
CMD_GRIP_CLOSE = b'GRIP_CLOSE\n'  # 吸附
CMD_GRIP_OPEN = b'GRIP_OPEN\n'    # 松开

def test_gripper():
    """测试气动夹爪"""
    try:
        # 打开串口
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=TIMEOUT)
        print(f"已连接到 {SERIAL_PORT} @ {BAUD_RATE}")
        time.sleep(2)  # 等待STM32初始化

        cycle = 0
        while True:
            cycle += 1

            # 吸附
            print(f"\n[周期 {cycle}] 发送: GRIP_CLOSE (吸附)")
            ser.write(CMD_GRIP_CLOSE)
            ser.flush()
            time.sleep(1.0)

            # 松开
            print(f"[周期 {cycle}] 发送: GRIP_OPEN (松开)")
            ser.write(CMD_GRIP_OPEN)
            ser.flush()
            time.sleep(1.0)

            # 读取回复（可选）
            if ser.in_waiting > 0:
                response = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                print(f"收到: {response.strip()}")

    except serial.SerialException as e:
        print(f"串口错误: {e}")
        print("\n可用串口:")
        import serial.tools.list_ports
        for port in serial.tools.list_ports.comports():
            print(f"  - {port.device}: {port.description}")
        sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n测试停止")
        ser.close()
        sys.exit(0)

    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == '__main__':
    print("=" * 50)
    print("气动夹爪测试 - 1秒吸附 / 1秒松开")
    print("=" * 50)
    print(f"串口: {SERIAL_PORT}")
    print(f"波特率: {BAUD_RATE}")
    print("按 Ctrl+C 停止测试")
    print("=" * 50)

    test_gripper()
