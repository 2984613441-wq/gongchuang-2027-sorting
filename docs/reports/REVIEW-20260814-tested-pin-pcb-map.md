# 实测引脚与 PCB 接口总图静态复核

日期：2026-08-14  
独立性：弱独立性（同一节点实施后静态复核）

## 结果

- 有效网络：29。
- 重复 GPIO：0。
- 与 `min-system-board-pinout.md` 不一致的排针位置：0。
- 旧 `UART_TX/UART_RX/J_UART` 唯一正式串口角色：0 处。
- 主/备 UART 接口引用：已覆盖 Markdown、Word 和 Excel。
- draw.io 与 SVG：XML 可解析；PNG 已完成像素预览检查。
- Word：ZIP/XML 可读，8 张表，1 张图片，旧 UART 接口引用为 0。
- Excel：5 张工作表，`PCB overview` 含 1 张图片，公式错误为 0。

## 限制

本复核只确认文档内部一致性，不证明 M144Z-M4 排针连续性、真实 EDA 网络、器件封装、ERC、DRC、Gerber、BOM、坐标文件或投板条件。
