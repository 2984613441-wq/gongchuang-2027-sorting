# 协议 V0.4 冻结子集

本目录只实现已经冻结且可独立测试的部分：四个关键命令的方案 B 方向、`DISPLAY_ACK` 六字节载荷、五字节规范显示内容及 CRC-32/ISO-HDLC、无状态消息到上下文领域事件的分层。

它不是完整外层帧实现。帧头、帧 CRC-16、CRC 覆盖范围、完整帧长度上限、UART、超时、重传和心跳仍未冻结，不在这里使用默认值猜定。

从仓库根目录运行：

```powershell
$env:PYTHONPATH=(Resolve-Path '电控\src').Path
python -m unittest discover -s '电控\tests\protocol' -v
```

`ProtocolCodec` 只校验方向并解析冻结载荷，输出 `DisplayAckMessage`。`DisplayAckContextValidator` 才使用当前件的期望显示内容生成 `DisplayAckReceived`。首次有效、重复消费和是否放行下一件仍由状态机负责。

V0.4 已冻结 `image_id` 的逻辑来源以及两端相同的单字节本轮成功计数规则。`ITEM_TASK` 的坐标/角度字节序等完整载荷编码、外层帧与STM32 C移植仍未冻结，因此当前仍不得宣称实机端到端内容匹配已经闭合。
