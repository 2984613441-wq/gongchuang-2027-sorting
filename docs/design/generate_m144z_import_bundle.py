from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


ROOT = Path(__file__).resolve().parent

JP_L = [
    ("PB15", "PF12"), ("PF0", "PF1"), ("PF2", "PF3"), ("PF4", "PD10"),
    ("PD9", "PD8"), ("PD14", "PE15"), ("PD15", "PE7"), ("PE8", "PE9"),
    ("PE14", "PE13"), ("PE12", "PE10"), ("PE11", "PF13"), ("PD13", "PD12"),
    ("PD11", "PF5"), ("PB13", "PB12"), ("PF6", "PF7"), ("PF8", "PF11"),
    ("PB2", "PB1"), ("PB0", "PC5"), ("PC4", "PA7"), ("PA5", "PA4"),
    ("PA3", "PC2"), ("PC3", "PA2"), ("PA1", "UREF"), ("RST", "3.3V"),
    ("GND", "3.3V"),
]

JP_R = [
    ("PC6", "PC7"), ("PD6", "PD7"), ("PG15", "PC10"), ("PC11", "PD2"),
    ("PC12", "PA8"), ("PC8", "PC9"), ("PG6", "PG7"), ("PG8", "PA11"),
    ("PA12", "PA6"), ("PB6", "PB5"), ("PB3", "PB11"), ("PB10", "PA15"),
    ("PD0", "PD1"), ("PD3", "PD4"), ("PD5", "PG9"), ("PG10", "PB7"),
    ("PE0", "PE1"), ("PC1", "PC0"), ("PE6", "PE5"), ("PE2", "PE3"),
    ("PG11", "PG12"), ("PG13", "PG14"), ("PB4", "VBAT"), ("GND", "5V"),
    ("GND", "5V"),
]

SIGNALS = {
    "PC6": ("STEP_X", "TIM8_CH1", "X 轴 STEP", "已实测输出；排针位置待验"),
    "PA7": ("DIR_X", "GPIO_OUT", "X 轴 DIR", "已实测输出；排针位置待验"),
    "PA5": ("ENABLE_X", "GPIO_OUT", "X 轴 ENABLE（低有效）", "已实测联动；排针位置待验"),
    "PB6": ("STEP_Y", "TIM4_CH1", "Y 轴 STEP", "已实测输出；排针位置待验"),
    "PC7": ("DIR_Y", "GPIO_OUT", "Y 轴 DIR", "已实测输出；排针位置待验"),
    "PD7": ("ENABLE_Y", "GPIO_OUT", "Y 轴 ENABLE（低有效）", "已实测联动；排针位置待验"),
    "PE5": ("STEP_Z", "TIM9_CH1", "Z 轴 STEP", "已实测输出；排针位置待验"),
    "PE6": ("DIR_Z", "GPIO_OUT", "Z 轴 DIR", "已实测输出；排针位置待验"),
    "PG15": ("ENABLE_Z", "GPIO_OUT", "Z 轴 ENABLE（低有效）", "已实测联动；排针位置待验"),
    "PB0": ("BARRIER_PWM_1", "TIM3_CH3", "挡板舵机 1 PWM", "已实测 PWM；排针位置待验"),
    "PB1": ("BARRIER_PWM_2", "TIM3_CH4", "挡板舵机 2 PWM", "已实测 PWM；排针位置待验"),
    "PF6": ("BARRIER_PWM_3", "TIM10_CH1", "挡板舵机 3 PWM", "已实测 PWM；排针位置待验"),
    "PF7": ("BARRIER_PWM_4", "TIM11_CH1", "挡板舵机 4 PWM", "已实测 PWM；排针位置待验"),
    "PB10": ("GRIP_PWM", "TIM2_CH3", "三指夹爪 PWM", "已实测 PWM；排针位置待验"),
    "PB11": ("WRIST_PWM", "TIM2_CH4", "腕部旋转预留 PWM", "DNP；排针位置待验"),
    "PC0": ("LIGHT_EN", "GPIO_OUT", "补光使能", "已实测输出；排针位置待验"),
    "PG7": ("X_HOME", "GPIO_IN_NOPULL", "X 原点限位", "外部 10k 上拉、低有效；排针位置待验"),
    "PG6": ("X_END", "GPIO_IN_NOPULL", "X 终点限位", "外部 10k 上拉、低有效；排针位置待验"),
    "PG9": ("Y_HOME", "GPIO_IN_NOPULL", "Y 原点限位", "外部 10k 上拉、低有效；排针位置待验"),
    "PD5": ("Y_END", "GPIO_IN_NOPULL", "Y 终点限位", "外部 10k 上拉、低有效；排针位置待验"),
    "PF11": ("Z_UP", "GPIO_IN_NOPULL", "Z 上限位", "外部 10k 上拉、低有效；排针位置待验"),
    "PG14": ("Z_DOWN", "GPIO_IN_NOPULL", "Z 下限位", "外部 10k 上拉、低有效；排针位置待验"),
    "PG13": ("ESTOP_FB", "GPIO_IN_NOPULL", "急停辅助反馈（只读）", "外部 10k 上拉、低有效；板载冲突待验"),
    "PA4": ("START_SIG", "GPIO_IN_NOPULL", "启动输入", "外部 10k 上拉、低有效；排针位置待验"),
    "PF8": ("MANUAL_RESET_SIG", "GPIO_IN_NOPULL", "人工复位输入", "外部 10k 上拉、低有效；排针位置待验"),
    "PA2": ("UART_MAIN_TX", "USART2_TX", "主 UART TX -> 树莓派 RX", "已实测 115200 8N1；2026-08-30 用户拍板主链路"),
    "PA3": ("UART_MAIN_RX", "USART2_RX", "主 UART RX <- 树莓派 TX", "已实测 115200 8N1；2026-08-30 用户拍板主链路"),
    "PD8": ("UART_BACKUP_TX", "USART3_TX", "备用 UART TX", "已实测 115200 8N1；2026-08-30 起为备用"),
    "PD9": ("UART_BACKUP_RX", "USART3_RX", "备用 UART RX", "已实测 115200 8N1；2026-08-30 起为备用"),
}

SPECIAL = {
    "GND": ("GND_LOGIC", "POWER", "逻辑地", "必须接公共逻辑地；不作为电机/舵机动力回路"),
    "5V": ("VLOGIC_5V", "POWER_IN", "主控 5V 主供电候选", "外部 DC/DC 5V 候选；与 3.3V 备选/USB 供电互斥；输入方向和额定待验"),
    "3.3V": ("VLOGIC_3V3_BACKUP", "POWER_BACKUP", "主控 3.3V 备选供电/参考", "仅作备选；必须确认可直接输入；与 5V/USB 互斥，不得默认同时连接"),
    "UREF": ("", "TBD", "UREF 用途待确认", "不贴网络标签；暂不连接，确认定义后再处理"),
    "RST": ("", "SYSTEM", "主控复位脚", "当前不接硬件复位则放不连接标记；若使用再命名 MCU_NRST"),
    "VBAT": ("", "SYSTEM", "RTC 备用电源", "不使用则放不连接标记；不得接 5V"),
}


def pin_rows():
    rows = []
    for side, pins in (("JP_L", JP_L), ("JP_R", JP_R)):
        for row, (outer, inner) in enumerate(pins, 1):
            for col, gpio in (("外列", outer), ("内列", inner)):
                num = (row - 1) * 2 + (1 if col == "外列" else 2)
                if gpio in SPECIAL:
                    role, alt, function, status = SPECIAL[gpio]
                elif gpio in SIGNALS:
                    role, alt, function, status = SIGNALS[gpio]
                else:
                    role, alt, function, status = ("", "UNASSIGNED", "未分配 GPIO", "不用则放不连接标记；若作备用，必须使用独立网名并引出测试点")
                rows.append({
                    "排针": side, "行": row, "列": col, "物理针号": num,
                    "GPIO/板载名": gpio, "功能/定时器": alt, "设计网名": role,
                    "功能说明": function, "状态/证据边界": status,
                })
    return rows


def legacy_pin(name, number, x, y, orient):
    return f"X {name} {number} {x} {y} 100 {orient} 45 45 1 1 B"


def legacy_symbol(name, pins, description):
    lines = [
        f"#",
        f"# {name}",
        f"#",
        f"DEF {name} J 0 40 Y Y 1 F N",
        f"F0 \"J\" 0 700 60 H V C CNN",
        f"F1 \"{description}\" 0 600 50 H V C CNN",
        "DRAW",
        "S -500 550 500 -550 0 1 12 f",
    ]
    for row, (outer, inner) in enumerate(pins, 1):
        y = 500 - (row - 1) * 40
        lines.append(legacy_pin(outer, (row - 1) * 2 + 1, -600, y, "R"))
        lines.append(legacy_pin(inner, (row - 1) * 2 + 2, 600, y, "L"))
    lines.extend(["ENDDRAW", "ENDDEF"])
    return "\n".join(lines) + "\n"


def kicad_pin(name, number, x, y, angle):
    return (
        f'    (pin bidirectional line (at {x} {y} {angle}) (length 2.54)\n'
        f'      (name "{name}" (effects (font (size 1 1))))\n'
        f'      (number "{number}" (effects (font (size 1 1))))\n'
        f'    )'
    )


def kicad_symbol(name, pins, description):
    lines = [
        f'  (symbol "{name}"',
        '    (pin_names (offset 1.016))',
        '    (exclude_from_sim no)',
        '    (in_bom yes)',
        '    (on_board yes)',
        f'    (property "Reference" "J" (at 0 18 0) (effects (font (size 1.27 1.27))))',
        f'    (property "Value" "{description}" (at 0 16 0) (effects (font (size 1.27 1.27))))',
        f'    (property "Description" "{description}; pin positions from user-recorded M144Z-M4 2x25 headers; candidate, unverified" (at 0 0 0) (effects (font (size 1 1)) hide))',
        f'    (symbol "{name}_0_1"',
        '      (rectangle (start -12.7 14) (end 12.7 -14) (stroke (width 0) (type default)) (fill (type background)))',
        '    )',
        f'    (symbol "{name}_1_1"',
    ]
    for row, (outer, inner) in enumerate(pins, 1):
        y = 12.7 - (row - 1) * 0.96
        lines.append(kicad_pin(outer, (row - 1) * 2 + 1, -15.24, y, 0))
        lines.append(kicad_pin(inner, (row - 1) * 2 + 2, 15.24, y, 180))
    lines.extend(['    )', '  )'])
    return "\n".join(lines)


def write_symbol_libraries():
    legacy_symbols = [
        legacy_symbol("M144Z_M4_JP_L", JP_L, "M144Z-M4 JP_L 2x25"),
        legacy_symbol("M144Z_M4_JP_R", JP_R, "M144Z-M4 JP_R 2x25"),
    ]
    legacy = ["EESchema-LIBRARY Version 2.4", "#encoding utf-8", *legacy_symbols, "#End Library"]
    (ROOT / "M144Z-M4_CARRIER.lib").write_text("\n".join(legacy) + "\n", encoding="utf-8")

    modern = [
        '(kicad_symbol_lib (version 20231120) (generator kicad_symbol_editor)',
        kicad_symbol("M144Z_M4_JP_L", JP_L, "M144Z-M4 JP_L 2x25"),
        kicad_symbol("M144Z_M4_JP_R", JP_R, "M144Z-M4 JP_R 2x25"),
        ')',
    ]
    (ROOT / "M144Z-M4_CARRIER.kicad_sym").write_text("\n".join(modern) + "\n", encoding="utf-8")


def write_legacy_schematic():
    # Legacy KiCad schematic is intentionally self-contained with a cache library;
    # EasyEDA Standard's KiCad importer can consume this as a complete schematic.
    lib = (ROOT / "M144Z-M4_CARRIER.lib").read_text(encoding="utf-8")
    (ROOT / "M144Z-M4_CARRIER-cache.lib").write_text(lib, encoding="utf-8")
    schematic = """EESchema Schematic File Version 4
LIBS:M144Z-M4_CARRIER-cache
EELAYER 29 0
EELAYER END
$Descr A4 11693 8268
Sheet 1 1
Title "M144Z-M4 Mini Board JP_L/JP_R Pinout"
Date "2026-08-15"
Rev "G1-CANDIDATE"
Comp "Candidate import reference - physical header positions TBD"
Comment1 "JP_L/JP_R: odd pins outer column, even pins inner column"
Comment2 "GPIO function evidence is from user tests; header continuity remains to be verified"
$EndDescr
$Comp
L M144Z_M4_JP_L J1
U 1 1 1
P 3300 4000
F 0 "J1" H 3300 4725 60  0000 C CNN
F 1 "M144Z_M4_JP_L" H 3300 4625 50  0000 C CNN
	1    3300 4000
	1    0    0    -1
$EndComp
$Comp
L M144Z_M4_JP_R J2
U 1 1 2
P 7500 4000
F 0 "J2" H 7500 4725 60  0000 C CNN
F 1 "M144Z_M4_JP_R" H 7500 4625 50  0000 C CNN
	1    7500 4000
	1    0    0    -1
$EndComp
Text Notes 3300 5200 0    80   ~ 16
JP_L: 1=PB15 outer, 2=PF12 inner; row numbering from TF-card end
Text Notes 7500 5200 0    80   ~ 16
JP_R: 1=PC6 outer, 2=PC7 inner; row numbering from TF-card end
Text Notes 5500 5800 0    70   ~ 12
G1 candidate pinout reference. Do not freeze PCB until header continuity and mechanical dimensions are verified.
$EndSCHEMATC
"""
    (ROOT / "M144Z-M4_CARRIER.sch").write_text(schematic, encoding="utf-8")


def write_csv(rows):
    path = ROOT / "M144Z-M4_CARRIER_pinmap.csv"
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_svg(rows):
    width, height = 1800, 1700
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<style>text{font-family:Arial,"Microsoft YaHei",sans-serif} .title{font-size:30px;font-weight:700} .hdr{font-size:18px;font-weight:700} .pin{font-size:14px} .note{font-size:15px}</style>',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="900" y="45" text-anchor="middle" class="title">M144Z-M4 Mini Board 完整 2×25 排针物理针位图（候选/待验）</text>',
        '<text x="900" y="75" text-anchor="middle" class="note">奇数=外列，偶数=内列；行号从 TF 卡端开始；针号为实物排针编号，不是 MCU 封装脚号</text>',
    ]
    for x, side, pins in ((80, "JP_L", JP_L), (940, "JP_R", JP_R)):
        lines.append(f'<rect x="{x}" y="110" width="780" height="1450" rx="10" fill="#fff4cf" stroke="#c79518" stroke-width="2"/>')
        lines.append(f'<text x="{x+390}" y="145" text-anchor="middle" class="hdr">{side}（2×25）</text>')
        lines.append(f'<text x="{x+110}" y="175" text-anchor="middle" class="note">外列 / 奇数</text>')
        lines.append(f'<text x="{x+670}" y="175" text-anchor="middle" class="note">内列 / 偶数</text>')
        for row, (outer, inner) in enumerate(pins, 1):
            y = 205 + (row - 1) * 51
            for col, gpio in (("外列", outer), ("内列", inner)):
                num = (row - 1) * 2 + (1 if col == "外列" else 2)
                meta = SIGNALS.get(gpio)
                net = meta[0] if meta else SPECIAL.get(gpio, ("", "", "", ""))[0]
                display = net or ("NC / TBD" if gpio in SPECIAL else "NC / SPARE")
                color = "#d9f0d0" if meta else ("#f8dfc2" if gpio in SPECIAL else "#eeeeee")
                tx = x + (50 if col == "外列" else 410)
                anchor = "start"
                lines.append(f'<rect x="{tx-22}" y="{y-18}" width="335" height="36" fill="{color}" stroke="#aaaaaa"/>')
                lines.append(f'<text x="{tx-12}" y="{y-4}" class="pin">{num:02d}  {gpio}</text>')
                lines.append(f'<text x="{tx-12}" y="{y+13}" class="pin">{display}</text>')
        lines.append(f'<text x="{x+390}" y="1535" text-anchor="middle" class="note">GPIO 复用已实测不等于排针连续性已验证</text>')
    lines.extend([
        '<rect x="80" y="1590" width="1640" height="60" fill="#f5d1d1" stroke="#be4b4b"/>',
        '<text x="900" y="1627" text-anchor="middle" class="note">来源：用户 2026-08-13 手工抄录；JP_R-1=PC6 外列、JP_R-2=PC7 内列；冻结前必须 1:1 打印/万用表连续性核对</text>',
        '</svg>',
    ])
    (ROOT / "M144Z-M4_CARRIER_pinmap.svg").write_text("\n".join(lines), encoding="utf-8")


def update_workbook(rows):
    source = ROOT / "G1候选原理图绘制清单.xlsx"
    path = ROOT / "G1候选原理图绘制清单-供电更新版.xlsx"
    wb = load_workbook(source)
    if "完整物理针位" in wb.sheetnames:
        del wb["完整物理针位"]
    if "导入文件" in wb.sheetnames:
        del wb["导入文件"]
    ws = wb.create_sheet("完整物理针位")
    headers = list(rows[0])
    ws.append(headers)
    for row in rows:
        ws.append([row[h] for h in headers])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for col in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(col)].width = [10, 7, 9, 12, 14, 18, 22, 26, 34][col - 1]

    ws2 = wb.create_sheet("导入文件")
    ws2.append(["文件", "用途", "导入/查看方式", "状态与限制"])
    entries = [
        ("M144Z-M4_CARRIER.sch", "完整 KiCad Legacy 原理图", "立创 EDA 标准版：文件 → 导入 → KiCad...；优先选择此文件", "已放置 JP_L/JP_R；G1 候选，未在立创 GUI 中实开验证"),
        ("M144Z-M4_CARRIER-cache.lib", "SCH 配套缓存库", "与 .sch 放在同一目录，不单独导入", "由 .sch 自动引用"),
        ("M144Z-M4_CARRIER.lib", "兼容库", "立创 EDA 导入 KiCad/Legacy .lib；放置 M144Z_M4_JP_L / M144Z_M4_JP_R", "候选库，未在立创 GUI 中实开验证"),
        ("M144Z-M4_CARRIER.kicad_sym", "KiCad 符号库", "KiCad/支持 KiCad 库导入的 EDA 版本", "候选库，未在立创 GUI 中实开验证"),
        ("M144Z-M4_CARRIER_pinmap.csv", "完整针位表", "Excel/文本查看；用于逐针核对", "100 个排针位置，物理位置来源仍待验"),
        ("M144Z-M4_CARRIER_pinmap.svg", "完整可视对照图", "浏览器直接打开或导入文档", "显示外列/内列和已用网名"),
    ]
    for entry in entries:
        ws2.append(entry)
    for cell in ws2[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for row in ws2.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for col, width in enumerate((34, 20, 58, 42), 1):
        ws2.column_dimensions[get_column_letter(col)].width = width

    ws3 = wb.create_sheet("供电选择")
    ws3.append(["项目", "当前候选", "原理图网名", "使用条件", "禁止事项", "证据状态"])
    power_rows = [
        ("主供电", "外部 DC/DC 输出 5V", "VLOGIC_5V", "接 M144Z-M4 5V 排针；建议串入供电选择跳线", "不得与 USB/3.3V 备选同时供电", "候选方案；M144Z-M4 5V 输入方向/额定待官方资料或实物确认"),
        ("备选供电", "外部稳定 3.3V", "VLOGIC_3V3_BACKUP", "仅在确认 3.3V 排针允许直接输入后使用", "不得与 5V/USB 同时连接；不得给舵机/电机供电", "候选备选；尚未证明可直接输入"),
        ("逻辑地", "所有逻辑接口公共地", "GND_LOGIC", "主控、树莓派 UART、外部驱动控制侧共参考", "不得用急停切断公共逻辑地", "设计边界已确定"),
        ("3.3V 排针", "主控板 3.3V 脚", "VLOGIC_3V3_BACKUP", "只作为备选输入/参考，具体方向待验", "不得把它当成 5V 或舵机电源", "板载电源关系待验"),
        ("电机/舵机动力", "外部独立电源模块", "VMOT_ESTOP / V_SERVO_5V", "分别供 A4988/外部驱动器和舵机", "不得从 M144Z-M4 3.3V/5V 排针取大电流", "板外模块边界已确定"),
    ]
    for row in power_rows:
        ws3.append(row)
    for cell in ws3[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for row in ws3.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for col, width in enumerate((18, 28, 26, 48, 46, 52), 1):
        ws3.column_dimensions[get_column_letter(col)].width = width
    wb.save(path)


def main():
    rows = pin_rows()
    assert len(rows) == 100
    assert len({(r["排针"], r["物理针号"]) for r in rows}) == 100
    write_symbol_libraries()
    write_legacy_schematic()
    write_csv(rows)
    write_svg(rows)
    update_workbook(rows)
    print(f"generated {len(rows)} physical pins")


if __name__ == "__main__":
    main()
