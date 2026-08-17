from copy import copy
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


root = Path(r"C:\Users\29845\Desktop\工创赛")
source = root / "docs" / "design" / "G1候选原理图绘制清单-供电更新版.xlsx"
target = root / "docs" / "design" / "G1候选原理图绘制清单-板外驱动接线版.xlsx"

wb = load_workbook(source)

# Align legacy interface rows with the external-driver decision used by the new sheets.
summary = wb["接口汇总"]
for row in summary.iter_rows(min_row=2):
    name = row[0].value
    if name in {"J_DRV_X_CTRL", "J_DRV_Y_CTRL", "J_DRV_Z_CTRL"}:
        row[1].value = "4"
        row[2].value = "STEP/DIR/ENABLE/GND_LOGIC"
        row[3].value = "候选安装"
        row[4].value = "XH2.54-4P；A4988、电机、VMOT均在板外"
    elif name == "J_LOGIC_PWR_IN":
        row[1].value = "2+2"
        row[2].value = "5V主供电或3.3V备选/GND"
        row[3].value = "候选安装"
        row[4].value = "详见电源接口；两路互斥，3.3V默认DNP"

pending = wb["待定与不放置"]
for row in pending.iter_rows(min_row=2):
    if row[1].value == "A4988 针序、封装、限流、散热":
        row[2].value = "不放在STM32载板；外部驱动器资料待确认"
        row[3].value = "当前采用板外驱动方案"

for name in ["板外驱动接线", "驱动器边界", "电源接口", "绘制顺序"]:
    if name in wb.sheetnames:
        del wb[name]

header_fill = PatternFill("solid", fgColor="1F4E78")
section_fill = PatternFill("solid", fgColor="D9EAF7")
header_font = Font(name="Arial", bold=True, color="FFFFFF")
body_font = Font(name="Arial", color="000000")
thin = Side(style="thin", color="B7C9D6")
border = Border(left=thin, right=thin, top=thin, bottom=thin)


def format_sheet(ws, widths):
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = body_font
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = border
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    ws.row_dimensions[1].height = 34


ws = wb.create_sheet("板外驱动接线")
ws.append([
    "轴/用途", "载板接口", "接口类型", "接口针号", "载板网络标签", "GPIO来源",
    "外部驱动器端", "外部电源/电机连接", "状态/备注"
])
rows = [
    ["X轴控制", "J_DRV_X_CTRL", "XH2.54-4P", 1, "STEP_X", "PC6", "STEP", "不接动力电源", "板外驱动控制"],
    ["X轴控制", "J_DRV_X_CTRL", "XH2.54-4P", 2, "DIR_X", "PA7", "DIR", "不接动力电源", "板外驱动控制"],
    ["X轴控制", "J_DRV_X_CTRL", "XH2.54-4P", 3, "ENABLE_X", "PA5", "ENABLE（低有效）", "不接动力电源", "板外驱动控制"],
    ["X轴控制", "J_DRV_X_CTRL", "XH2.54-4P", 4, "GND_LOGIC", "公共逻辑地", "信号地", "与外部驱动器逻辑地共地", "必须连接"],
    ["Y轴控制", "J_DRV_Y_CTRL", "XH2.54-4P", 1, "STEP_Y", "PB6", "STEP", "不接动力电源", "板外驱动控制"],
    ["Y轴控制", "J_DRV_Y_CTRL", "XH2.54-4P", 2, "DIR_Y", "PC7", "DIR", "不接动力电源", "板外驱动控制"],
    ["Y轴控制", "J_DRV_Y_CTRL", "XH2.54-4P", 3, "ENABLE_Y", "PD7", "ENABLE（低有效）", "不接动力电源", "板外驱动控制"],
    ["Y轴控制", "J_DRV_Y_CTRL", "XH2.54-4P", 4, "GND_LOGIC", "公共逻辑地", "信号地", "与外部驱动器逻辑地共地", "必须连接"],
    ["Z轴控制", "J_DRV_Z_CTRL", "XH2.54-4P", 1, "STEP_Z", "PE5", "STEP", "不接动力电源", "板外驱动控制"],
    ["Z轴控制", "J_DRV_Z_CTRL", "XH2.54-4P", 2, "DIR_Z", "PE6", "DIR", "不接动力电源", "板外驱动控制"],
    ["Z轴控制", "J_DRV_Z_CTRL", "XH2.54-4P", 3, "ENABLE_Z", "PG15", "ENABLE（低有效）", "不接动力电源", "板外驱动控制"],
    ["Z轴控制", "J_DRV_Z_CTRL", "XH2.54-4P", 4, "GND_LOGIC", "公共逻辑地", "信号地", "与外部驱动器逻辑地共地", "必须连接"],
    ["X电机", "外部驱动器端子", "不放在STM32载板", "—", "X_MOTOR_1A/1B/2A/2B", "驱动器输出", "1A/1B/2A/2B", "外部驱动器→X电机", "不经过本载板；线序按电机资料确认"],
    ["Y电机", "外部驱动器端子", "不放在STM32载板", "—", "Y_MOTOR_1A/1B/2A/2B", "驱动器输出", "1A/1B/2A/2B", "外部驱动器→Y电机", "不经过本载板；线序按电机资料确认"],
]
for row in rows:
    ws.append(row)
format_sheet(ws, {"A": 14, "B": 20, "C": 17, "D": 10, "E": 22, "F": 17, "G": 20, "H": 28, "I": 24})

ws = wb.create_sheet("驱动器边界")
ws.append(["边界项目", "从哪里来", "接到哪里", "是否经过载板", "必须确认的内容", "当前候选规则"])
boundary_rows = [
    ["STEP/DIR/ENABLE", "STM32载板 J_DRV_*_CTRL", "板外 A4988 控制输入", "只经过逻辑信号", "外部模块输入端命名/电平", "3.3V逻辑候选"],
    ["GND_LOGIC", "STM32载板逻辑地", "板外驱动器信号地/VDD地", "经过4P接口", "共地方式和回流路径", "必须共地"],
    ["VDD", "外部逻辑电源或驱动器侧供电", "A4988 VDD", "不默认经过本载板", "模块允许3.3V还是5V、供电来源", "TBD；XH4不提供VDD"],
    ["VMOT_ESTOP", "外部电池/DC-DC及急停后动力电源", "A4988 VMOT", "不经过本载板逻辑区", "电压、电流、保险/急停拓扑", "外部处理；TBD"],
    ["GND_POWER", "外部动力电源负极", "A4988 VMOT GND", "不走逻辑信号线", "与GND_LOGIC单点汇接位置", "入口侧单点候选"],
    ["电机相线", "A4988 1A/1B/2A/2B", "X/Y 步进电机", "不经过STM32逻辑连接", "电机线序、端子额定、电流", "J_X_MOTOR/J_Y_MOTOR候选"],
    ["急停", "急停主回路", "动力电源切断链路", "不经过STM32载板", "急停器件和安全回路", "ESTOP_FB仅作只读反馈"],
]
for row in boundary_rows:
    ws.append(row)
format_sheet(ws, {"A": 18, "B": 30, "C": 34, "D": 22, "E": 34, "F": 28})

ws = wb.create_sheet("电源接口")
ws.append(["接口/器件", "接口类型", "针号", "网络标签", "接入来源", "接到哪里", "状态与互斥规则"])
power_rows = [
    ["J_LOGIC_5V_IN", "XH2.54-2P", 1, "VLOGIC_5V", "板外 DC/DC 稳定5V输出正极", "M144Z-M4 右排左侧物理列（H2 当前符号 47/49）", "主供电候选；禁止与3.3V备选、USB同时并接"],
    ["J_LOGIC_5V_IN", "XH2.54-2P", 2, "GND_LOGIC", "板外 DC/DC 输出负极", "M144Z-M4 右排右侧物理列（H2 当前符号 48/50）及公共逻辑地", "必须接；与外部驱动器信号地共参考"],
    ["J_LOGIC_3V3_BACKUP", "XH2.54-2P，默认DNP", 1, "VLOGIC_3V3_BACKUP", "板外稳定3.3V输出正极", "M144Z-M4 左排 3.3V 脚（JP_L-48/50，按实物针位）", "备选供电；只有确认3.3V排针可直接输入后才能使用"],
    ["J_LOGIC_3V3_BACKUP", "XH2.54-2P，默认DNP", 2, "GND_LOGIC", "板外3.3V输出负极", "公共逻辑地", "与5V输入互斥；不能把两个输入正极并接"],
    ["J_DRV_POWER_X/Y/Z", "板外端子，不并入逻辑XH", "—", "VMOT_ESTOP/GND_POWER", "外部电池/DC-DC及急停后的动力电源", "板外 A4988 的 VMOT/GND", "动力电源不经过STM32载板逻辑接口；端子和额定待定"],
    ["J_SERVO_POWER", "板外端子，不并入逻辑XH", "—", "V_SERVO_5V/GND_POWER", "外部舵机5V电源", "舵机供电分配", "载板只出PWM/GND_LOGIC；不从M144Z逻辑5V给舵机供电"],
]
for row in power_rows:
    ws.append(row)
format_sheet(ws, {"A": 24, "B": 24, "C": 10, "D": 26, "E": 36, "F": 42, "G": 44})

ws = wb.create_sheet("绘制顺序")
ws.append(["顺序", "原理图页面/模块", "先放什么", "连接规则", "完成检查"])
order_rows = [
    [1, "MCU_CARRIER", "H1/H2 两排主控排针", "按实物丝印和当前已确认标签", "H2 不再按旧 JP_R 奇偶表镜像"],
    [2, "EXTERNAL_DRIVER_CTRL", "J_DRV_X/Y/Z_CTRL，各 XH2.54-4P", "STEP/DIR/ENABLE/GND_LOGIC", "每个接口1脚方向清楚"],
    [3, "外部驱动器/电机边界", "不在STM32载板放J_X_MOTOR/J_Y_MOTOR", "电机四相线留在外部驱动器侧", "确认外部驱动器端子和电机线序"],
    [4, "UART", "J_UART_MAIN、J_UART_BACKUP", "TX/RX/GND_LOGIC，主备不并接", "TX/RX方向检查"],
    [5, "SAFETY_AND_INPUTS", "限位、START、RESET、ESTOP_FB接口", "信号+GND，调理器件位保留", "输入触发逻辑不串线"],
    [6, "SERVO_GRIPPER_LIGHT", "四路挡板、夹爪、腕部DNP、补光", "PWM+GND_LOGIC", "舵机动力电源不从逻辑接口取"],
    [7, "LOGIC_POWER", "5V主供电、3.3V备选、逻辑地", "5V/3.3V互斥，USB不并接", "VLOGIC_5V与VLOGIC_3V3_BACKUP不短接"],
    [8, "TEST_POINTS", "STEP/DIR/ENABLE/PWM/UART/电源测试点", "每路独立网名", "测试点不改变主网络"],
]
for row in order_rows:
    ws.append(row)
format_sheet(ws, {"A": 10, "B": 24, "C": 34, "D": 42, "E": 36})

wb.save(target)
print(target)
