# test10 输入分组测试静态复核

日期：2026-08-14  
独立性：弱独立性（同一节点实施后静态检查）

- `.ioc` 中五路输入均为 `GPIO_Input + GPIO_PULLUP`。
- `PD8/PD9` 在 HAL MSP 中配置为 `USART3_TX/USART3_RX`，复用 `GPIO_AF7_USART3`。
- `main.c` 读取端口与角色映射一致，并以 500 ms 周期输出状态。
- 本记录不构成实际串口、排针连续性或安全回路通过证明。
