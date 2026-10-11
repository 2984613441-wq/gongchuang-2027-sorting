#!/usr/bin/env python3
"""Motion parameter calibration tool.

Run this script with real hardware to measure actual motion parameters.
Results are saved to motion_config.json for production use.

Usage:
    python calibrate_motion.py
"""

import time
from pathlib import Path

from electrical_control.scheduler import MotionConfig, save_motion_config


def measure_linear_motion(distance_mm: float = 100.0, trials: int = 10) -> float:
    """Measure linear motion speed in XY plane.

    Args:
        distance_mm: Distance to move (default 100mm)
        trials: Number of measurements (default 10)

    Returns:
        Average speed in mm/s
    """
    print(f"\n=== 线性运动速度标定 ===")
    print(f"距离: {distance_mm}mm")
    print(f"测试次数: {trials}")
    print("\n请按照提示操作STM32执行往返运动，测量每次所需时间\n")

    times = []
    for i in range(trials):
        input(f"第{i+1}/{trials}次测试 - 按回车开始移动...")
        start = time.time()
        input(f"移动{distance_mm}mm完成后按回车...")
        elapsed = time.time() - start
        times.append(elapsed)
        speed = distance_mm / elapsed
        print(f"  用时: {elapsed:.2f}s, 速度: {speed:.1f}mm/s")

    avg_time = sum(times) / len(times)
    avg_speed = distance_mm / avg_time

    print(f"\n平均用时: {avg_time:.2f}s")
    print(f"平均速度: {avg_speed:.1f}mm/s")

    return avg_speed


def measure_pick_action(trials: int = 10) -> tuple[float, float]:
    """Measure complete pick action time.

    Args:
        trials: Number of measurements (default 10)

    Returns:
        (total_pick_time, z_axis_time) in seconds
    """
    print(f"\n=== 夹取动作时间标定 ===")
    print(f"测试次数: {trials}")
    print("\n请测量完整夹取流程: Z下降 → 夹爪闭合 → Z上升\n")

    total_times = []
    for i in range(trials):
        input(f"第{i+1}/{trials}次测试 - 按回车开始夹取...")
        start = time.time()
        input("夹取完成（Z轴回到原位）后按回车...")
        elapsed = time.time() - start
        total_times.append(elapsed)
        print(f"  用时: {elapsed:.2f}s")

    avg_total = sum(total_times) / len(total_times)
    print(f"\n平均夹取时间: {avg_total:.2f}s")

    # 测量Z轴时间
    print(f"\n现在单独测量Z轴上下运动时间（不含夹爪动作）")
    z_times = []
    for i in range(trials):
        input(f"第{i+1}/{trials}次测试 - 按回车开始Z轴移动...")
        start = time.time()
        input("Z轴回到原位后按回车...")
        elapsed = time.time() - start
        z_times.append(elapsed)
        print(f"  用时: {elapsed:.2f}s")

    avg_z = sum(z_times) / len(z_times)
    print(f"\n平均Z轴时间: {avg_z:.2f}s")

    # XY平面夹取时间 = 总时间 - Z轴时间
    xy_pick_time = avg_total - avg_z

    return xy_pick_time, avg_z


def main():
    """Run calibration and save results."""
    print("=" * 60)
    print("运动参数标定工具")
    print("=" * 60)
    print("\n警告: 请确保设备已正确连接且处于安全状态")
    input("\n按回车开始标定...")

    # Measure linear motion speed
    motion_speed = measure_linear_motion(distance_mm=100.0, trials=10)

    # Measure pick action time
    pick_time, z_time = measure_pick_action(trials=10)

    # Create config
    config = MotionConfig(
        motion_speed_mm_per_s=motion_speed,
        pick_action_time_s=pick_time,
        z_axis_time_s=z_time,
    )

    # Display results
    print("\n" + "=" * 60)
    print("标定结果")
    print("=" * 60)
    print(f"线性运动速度: {config.motion_speed_mm_per_s:.1f} mm/s")
    print(f"XY平面夹取时间: {config.pick_action_time_s:.2f} s")
    print(f"Z轴运动时间: {config.z_axis_time_s:.2f} s")
    print(f"总夹取时间: {config.total_pick_time_s:.2f} s")
    print("=" * 60)

    # Save to file
    output_file = Path(__file__).parent / "motion_config.json"
    save_motion_config(config, str(output_file))

    print(f"\n✅ 配置已保存到: {output_file}")
    print("\n使用方法:")
    print("  from electrical_control.scheduler import load_motion_config")
    print(f"  config = load_motion_config('{output_file}')")
    print("  scheduler = PhasedScheduler(motion_config=config)")


if __name__ == '__main__':
    main()
