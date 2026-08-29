# 主机侧链接口契约（2026-08-29）— 树莓派出站发送 / 显示渲染 / 集成闭环

> 状态：本轮接口冻结提案（主机侧纯逻辑）。串口波特率、真实渲染、相机等硬件参数
> **不在此处写死**，一律由部署配置/注入提供。未冻结的 BATCH_TARGETS 线格式不涉及。
> 依据：赛题问题二（27年工创.pdf P9~13）+ 要求汇总 §5（方案 B 主链）+ 硬件映射待确认表。

## 1. 串口链路抽象（供出站发送器与未来入站接收复用）

模块：`电控/src/electrical_control/rpi/serial_link.py`

```python
class SerialLink(Protocol):
    """One complete outer frame per send/receive; never exposes wire details."""
    def send(self, frame: bytes) -> None: ...
    def receive(self) -> bytes | None: ...   # None = nothing buffered yet

class FakeSerialLink:
    """Records outbound frames; deterministic inbound queue for host tests."""
    def __init__(self) -> None: ...
    @property
    def sent(self) -> tuple[bytes, ...]: ...   # all frames sent so far
    def queue_inbound(self, frame: bytes) -> None: ...  # for tests
    def send(self, frame: bytes) -> None: ...
    def receive(self) -> bytes | None: ...
```

- 生产实现（如 pyserial）由部署注入；**波特率/端口不写死**。
- 入站解析（feed_byte 重同步）已在 `PiProtocolGateway` 实现，本契约不重复。

## 2. 出站发送器（树莓派 → STM32）

模块：`电控/src/electrical_control/rpi/outbound.py`

```python
@dataclass(frozen=True, slots=True)
class OutboundConfig:
    round_task_id: int   # 本轮任务号（来自 VerifiedNewRound，u16 范围校验）

class OutboundGateway:
    """Encodes and sends ITEM_TASK / DISPLAY_ACK outer frames over a SerialLink."""
    def __init__(self, link: SerialLink, *, config: OutboundConfig) -> None: ...
    @property
    def tx_seq(self) -> int: ...          # 单调递增（1 起），每发一帧 +1
    def send_item_task(self, task: ItemTaskContext) -> bytes:
        """Encode task.payload via encode_item_task_frame(task.task_id, seq, payload);
        requires task.task_id == config.round_task_id; returns the raw frame."""
    def send_display_ack(self, intent: DisplayAckIntent) -> bytes:
        """Reuse PiProtocolGateway.emit_display_ack semantics; returns raw frame."""
```

- 复用已冻结的 `electrical_control.protocol.encode_item_task_frame` /
  `encode_display_ack_frame`（帧格式冻结，见 outer_frame.py / frames.py）。
- `tx_seq` 独立于 `PiProtocolGateway.tx_seq`（入站侧），两者互不干扰。
- 非法 task_id（≠ round_task_id、超出 u16）必须拒绝并抛 `PayloadError`/`ValueError`（fail-closed）。

## 3. 显示渲染模块（树莓派 → HDMI 屏）

模块：`电控/src/electrical_control/rpi/display.py`

```python
@dataclass(frozen=True, slots=True)
class DisplayViewModel:
    """赛题要求的显示四项：序号 / 货物名称 / 图片 / 分拣成功总数量。"""
    target_seq: int
    name: str
    image_id: int
    success_count: int
    result_code: int

def build_display_view(content: DisplayContent,
                       names: Mapping[int, str],
                       image_ids: Mapping[int, int] | None = None) -> DisplayViewModel:
    """class_id -> 名称映射（树莓派本地），image_id 缺省取 content.image_id。"""

class DisplayRenderer(Protocol):
    """真实 HDMI 渲染由部署注入；host 用 FakeDisplayRenderer。"""
    def present(self, view: DisplayViewModel) -> PendingRender: ...
```

- `FakeRenderer`（rpi/__init__.py）保留，但新增 `FakeDisplayRenderer` 以 `DisplayViewModel`
  为输入，经 `PendingRender.complete()` 产出赛题闭环所需的 `RenderReceipt`。
- 名称映射来自树莓派本地 TF 卡（要求汇总 §5.2：只传类别 ID/图片 ID，不传图片文件）。

## 4. 集成闭环（赛题"显示完成后才能分拣下一件"端到端验证）

测试：`电控/tests/integration/test_host_side_chain.py`（全 fake，host 可跑）

链路（每件）：
```
build_item_task_queue(视觉 batch, image_id_for_class, drop_point_for_box)
  → Scheduler(FakeTaskSource) .next_task()
  → OutboundGateway.send_item_task()           # 帧经 FakeSerialLink 发出
  → 模拟 STM32：decode 外层帧校验 → 回 MOTION_DONE / ITEM_RESULT（经 gateway.feed_frame）
  → Scheduler.accept_item_result() → build_display_view(content, names)
  → FakeDisplayRenderer.present(view).complete() → accept_render_receipt()
  → OutboundGateway.send_display_ack()
  → 下一件（scheduler.next_task() 返回下一件）
```

断言点：
1. 每件只发送一条 ITEM_TASK；帧头/版本/CRC/大端字段可 decode 校验。
2. MOTION_DONE 门禁：未收 MOTION_DONE 前 ITEM_RESULT 被拒（FAULT/忽略）。
3. 未完成显示（无 render receipt）时 `next_task()` 返回 None（赛题 R-D04）。
4. 成功计数只在成功 ITEM_RESULT 后 +1，且显示的成功总数与计数一致。
5. 两件完整闭环后，`FakeSerialLink.sent` 帧序列 = [ITEM_TASK, DISPLAY_ACK, ITEM_TASK, DISPLAY_ACK]。

## 5. 边界

- 不新增任何冻结参数（波特率、GPIO、定时器、线格式一律注入）。
- 不触碰固件层（firmware/）、MaixCAM 线格式（未冻结）。
- 全部 host 测试；无上电/串口/相机/实机操作。
