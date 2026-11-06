# 协议 V0.5 冻结子集

本目录只实现已经冻结且可独立测试的部分：四个关键命令的方案 B 方向、`DISPLAY_ACK` 六字节载荷、五字节规范显示内容及 CRC-32/ISO-HDLC、无状态消息到上下文领域事件的分层。

它不是完整外层帧实现，本目录只处理已分帧的消息载荷。统一外层帧已在 V0.5 冻结（帧头 `0xA5 0x5A`、帧 CRC=CRC-16/MODBUS、`task_id`/`frame_seq`/`data_len` 大端）；完整帧长度上限、UART、超时、重传和心跳仍未冻结，不在这里使用默认值猜定。

从仓库根目录运行：

```powershell
$env:PYTHONPATH=(Resolve-Path '电控\src').Path
python -m unittest discover -s '电控\tests\protocol' -v
```

`ProtocolCodec` 只校验方向并解析冻结载荷，输出 `DisplayAckMessage`。`DisplayAckContextValidator` 才使用当前件的期望显示内容生成 `DisplayAckReceived`。首次有效、重复消费和是否放行下一件仍由状态机负责。

V0.5 已冻结 `image_id` 的逻辑来源、两端相同的单字节本轮成功计数规则，以及统一外层帧（帧头 `0xA5 0x5A`、帧 CRC=CRC-16/MODBUS）。`ITEM_TASK` 的 X/Y/角度字节序等完整载荷编码仍未冻结，因此当前仍不得宣称实机端到端内容匹配已经闭合。
