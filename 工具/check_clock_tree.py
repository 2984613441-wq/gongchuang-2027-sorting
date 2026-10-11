#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时钟树自检 —— 校验 main.c 的时钟配置与 7 个定时器 PSC/Period 是否自洽。

背景：2026-09-28 把主频从 HSI 16 MHz（PLL_NONE）改成 HSE 25 MHz + PLL = 168 MHz。
      7 个定时器的 Prescaler 必须同步改，漏一个就会让舵机 PWM 或步进频率错 5~10 倍。
      本脚本把这个"人容易漏"的一致性变成可复跑的检查。

判据分两类（重要）：
  * 舵机类（TIM2/TIM3/TIM10/TIM11）：PWM 输出频率 = 定时器钟/(PSC+1)/(Period+1)，必须是 50 Hz。
  * 步进类（TIM4/TIM8/TIM9）：**计数时钟** = 定时器钟/(PSC+1)，必须 = EC_STEP_TIMER_HZ（100 kHz）。
      ⇒ 它们的 Period(=9999) 只是初值，实际每步由 `__HAL_TIM_SET_AUTORELOAD(timer, reload)`
        按目标频率动态改写（见 ec_board_stm32.c 的 ec_step_profile_reload_at）。
      ⇒ 所以「PWM 输出频率」对这些定时器**没有意义**，不能拿来当判据。

用法（工作区根目录）：
    py -3 工具/check_clock_tree.py
退出码：0 = 全部自洽；1 = 有不自洽项（逐条打印）。

只读：本脚本不修改任何文件。输出刻意使用 ASCII，避免 GBK 控制台编码报错。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FW = ROOT / "电控" / "firmware" / "stm32f407_m144z"
MAIN_C = FW / "Core" / "Src" / "main.c"
HAL_CONF = FW / "Core" / "Inc" / "stm32f4xx_hal_conf.h"
BOARD_C = FW / "App" / "Src" / "ec_board_stm32.c"
SYSC_C = FW / "Core" / "Src" / "system_stm32f4xx.c"

# (定时器, 总线, 判据类型, 期望值, 说明)
EXPECT = [
    ("TIM2", "APB1", "pwm", 50.0, "servo gripper/Z 50 Hz"),
    ("TIM3", "APB1", "pwm", 50.0, "servo barrier-ch 50 Hz"),
    ("TIM4", "APB1", "clk", 100_000.0, "STEP_Y counter clock == EC_STEP_TIMER_HZ"),
    ("TIM8", "APB2", "clk", 100_000.0, "STEP_X counter clock == EC_STEP_TIMER_HZ"),
    ("TIM9", "APB1", "clk", 100_000.0, "spare PWM counter clock"),
    ("TIM10", "APB2", "pwm", 50.0, "servo barrier-ch 50 Hz"),
    ("TIM11", "APB2", "pwm", 50.0, "servo barrier-ch 50 Hz"),
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def strip_comments(text: str) -> str:
    """剥掉 /* */ 与 // 注释。

    必须做这一步：本文件的改动带了很长的说明注释，注释里**举例提到了**
    `HAL_PWREx_EnableOverDrive()`、`PLL_NONE`、`SYSCLKSOURCE_HSI` 等字样，
    不剥注释就会把"注释里的举例"误判成"代码里真的这么干了"（实测踩过一次）。
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def find_int(text: str, pattern: str, label: str) -> int:
    m = re.search(pattern, text)
    if not m:
        print(f"  [FAIL] not found: {label} (regex {pattern!r})")
        sys.exit(1)
    return int(m.group(1))


def div_to_int(token: str) -> int:
    m = re.search(r"_DIV(\d+)", token)
    if not m:
        raise ValueError(f"cannot parse divider: {token!r}")
    return int(m.group(1))


def main() -> int:
    main_c, hal_conf = strip_comments(read(MAIN_C)), read(HAL_CONF)
    problems: list[str] = []

    print("=" * 78)
    print("STM32F407 clock-tree self-check  --  main.c / stm32f4xx_hal_conf.h")
    print("=" * 78)

    hse = find_int(hal_conf, r"#define\s+HSE_VALUE\s+(\d+)U?", "HSE_VALUE")
    pllm = find_int(main_c, r"PLL\.PLLM\s*=\s*(\d+)U?", "PLLM")
    plln = find_int(main_c, r"PLL\.PLLN\s*=\s*(\d+)U?", "PLLN")
    pllp = div_to_int(re.search(r"PLL\.PLLP\s*=\s*(\w+)", main_c).group(1))
    pllq = find_int(main_c, r"PLL\.PLLQ\s*=\s*(\d+)U?", "PLLQ")
    ahb = div_to_int(re.search(r"AHBCLKDivider\s*=\s*(\w+)", main_c).group(1))
    apb1 = div_to_int(re.search(r"APB1CLKDivider\s*=\s*(\w+)", main_c).group(1))
    apb2 = div_to_int(re.search(r"APB2CLKDivider\s*=\s*(\w+)", main_c).group(1))
    flash = re.search(r"FLASH_LATENCY_(\d+)", main_c)

    vco_in, vco_out = hse / pllm, (hse / pllm) * plln
    sysclk = vco_out / pllp
    hclk = sysclk / ahb
    pclk1, pclk2 = hclk / apb1, hclk / apb2
    tim_apb1 = pclk1 if apb1 == 1 else pclk1 * 2
    tim_apb2 = pclk2 if apb2 == 1 else pclk2 * 2

    print(f"  HSE                  = {hse/1e6:.4g} MHz")
    print(f"  PLL M/N/P/Q          = {pllm}/{plln}/{pllp}/{pllq}")
    print(f"  VCO in / out         = {vco_in/1e6:.4g} MHz / {vco_out/1e6:.4g} MHz")
    print(f"  SYSCLK               = {sysclk/1e6:.4g} MHz")
    print(f"  HCLK   (AHB /{ahb})    = {hclk/1e6:.4g} MHz")
    print(f"  PCLK1  (APB1/{apb1})   = {pclk1/1e6:.4g} MHz  -> APB1 timer clk = {tim_apb1/1e6:.4g} MHz")
    print(f"  PCLK2  (APB2/{apb2})   = {pclk2/1e6:.4g} MHz  -> APB2 timer clk = {tim_apb2/1e6:.4g} MHz")
    print(f"  PLLQ out             = {vco_out/pllq/1e6:.4g} MHz")
    print(f"  FLASH_LATENCY        = {flash.group(1) if flash else '?'} WS")
    print()

    if "RCC_PLL_NONE" in main_c:
        problems.append("PLL is still RCC_PLL_NONE (clock not raised to 168 MHz)")
    if "RCC_SYSCLKSOURCE_HSI" in main_c:
        problems.append("SYSCLKSource is still HSI (expected RCC_SYSCLKSOURCE_PLLCLK)")
    if "RCC_OSCILLATORTYPE_HSI" in main_c:
        problems.append("OscillatorType still contains HSI (expected HSE|LSI)")
    if abs(sysclk - 168e6) > 1e3:
        problems.append(f"SYSCLK = {sysclk/1e6:.4g} MHz, expected 168 MHz")
    if sysclk > 168e6 + 1:
        problems.append(f"SYSCLK {sysclk/1e6:.1f} MHz exceeds STM32F407 max 168 MHz")
    if pclk1 > 42e6 + 1:
        problems.append(f"PCLK1 {pclk1/1e6:.1f} MHz exceeds APB1 max 42 MHz")
    if pclk2 > 84e6 + 1:
        problems.append(f"PCLK2 {pclk2/1e6:.1f} MHz exceeds APB2 max 84 MHz")
    if flash and flash.group(1) != "5" and abs(sysclk - 168e6) < 1e3:
        problems.append("SYSCLK=168 MHz requires FLASH_LATENCY_5")
    if "EnableOverDrive" in main_c:
        problems.append("HAL_PWREx_EnableOverDrive() present -- STM32F407 has NO over-drive; "
                        "calling it waits on ODRDY that never sets -> HAL_TIMEOUT -> boot hang")

    # --- per-timer ---
    step_clk = None
    print(f"  {'TIM':<6}{'bus':<6}{'PSC':>6}{'Period':>8}{'measured':>14}  {'expect':>10}  note")
    print("  " + "-" * 74)
    for name, bus, kind, want, note in EXPECT:
        idx = name[3:]
        psc_m = re.search(rf"htim{idx}\.Init\.Prescaler\s*=\s*(\d+);", main_c)
        per_m = re.search(rf"htim{idx}\.Init\.Period\s*=\s*(\d+);", main_c)
        if not (psc_m and per_m):
            print(f"  [FAIL] {name}: Prescaler/Period not found")
            problems.append(f"{name}: cannot parse Prescaler/Period")
            continue
        psc, period = int(psc_m.group(1)), int(per_m.group(1))
        tclk = tim_apb1 if bus == "APB1" else tim_apb2
        clk = tclk / (psc + 1)                 # counter clock
        pwm = clk / (period + 1)               # PWM output frequency
        measured = pwm if kind == "pwm" else clk
        unit = "Hz"
        ok = abs(measured - want) <= max(want * 0.001, 0.01)
        if name == "TIM4":
            step_clk = clk
        print(f"  {'OK  ' if ok else 'FAIL'}{name:<2}{bus:<6}{psc:>6}{period:>8}"
              f"{measured:>14,.2f}  {want:>10,.0f}  {note}")
        if not ok:
            problems.append(f"{name}: measured {measured:,.2f} Hz != expected {want:,.0f} Hz "
                            f"(PSC={psc}, Period={period}, {bus} timer clk={tclk/1e6:.4g} MHz)")

    # --- EC_STEP_TIMER_HZ consistency ---
    print()
    if BOARD_C.exists() and step_clk is not None:
        m = re.search(r"#define\s+EC_STEP_TIMER_HZ\s+UINT32_C\((\d+)\)", read(BOARD_C))
        if m:
            macro = int(m.group(1))
            print(f"  EC_STEP_TIMER_HZ (ec_board_stm32.c) = {macro:,}")
            print(f"  TIM4 counter clock (measured)       = {step_clk:,.1f}")
            if abs(step_clk - macro) > 1:
                problems.append(f"EC_STEP_TIMER_HZ={macro} != TIM4 counter clock {step_clk:.0f} "
                                f"-> step frequency would be off by {step_clk/macro:.3f}x")
            else:
                print("  OK   consistent -> reload = round(timer_hz / target_hz) - 1 holds")

    # --- SystemCoreClock ---
    if SYSC_C.exists():
        m = re.search(r"uint32_t\s+SystemCoreClock\s*=\s*(\d+);", read(SYSC_C))
        if m:
            v = int(m.group(1))
            print()
            print(f"  SystemCoreClock initial value = {v:,}")
            if abs(v - sysclk) > 1:
                problems.append(f"SystemCoreClock={v} != computed SYSCLK={sysclk:.0f}")

    print()
    print("=" * 78)
    if problems:
        print(f"FAIL: {len(problems)} inconsistency(ies):")
        for i, p in enumerate(problems, 1):
            print(f"   {i}. {p}")
        print("=" * 78)
        return 1
    print("PASS: clock tree / 7 timers / EC_STEP_TIMER_HZ / SystemCoreClock all consistent.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
