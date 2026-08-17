# TASK-20260812-007 泳道 C TDD 证据

仅覆盖主机侧离线 fake 调度与显示骨架；未连接串口、GPIO、真实屏幕或执行器。

## 组 1：fake 任务源与恢复锁

- RED 命令：`$env:PYTHONPATH='电控/src'; python -m unittest discover -s '电控/tests/rpi' -p 'test_fake_source_and_recovery.py' -v`
- RED 退出码：`1`
- RED 用例数：加载器报告 `Ran 1 test`
- 首个失败：`ModuleNotFoundError: No module named 'electrical_control.rpi'`
- GREEN 命令：同上
- GREEN 退出码：`0`
- GREEN 用例数：`3`
- 首个失败：无

## 组 2：单件门禁、五字段模型、渲染凭据与 ACK 意图

- RED 命令：`$env:PYTHONPATH='电控/src'; python -m unittest discover -s '电控/tests/rpi' -p 'test_scheduler_rendering.py' -v`
- RED 退出码：`1`
- RED 用例数：加载器报告 `Ran 1 test`
- 首个失败：`ImportError: cannot import name 'FakeRenderer' from 'electrical_control.rpi'`
- 首次实现后的测试校正：12 个用例中 11 个通过，1 个失败；首个失败为非固定显示模型错误断言 CRC 末字节 `0xF4`。删除该错误断言，保留独立冻结向量 `01 02 03 04 05 -> 0x470B99F4`，生产逻辑未因错误断言调整。
- GREEN 命令：同上
- GREEN 退出码：`0`
- GREEN 用例数：`12`
- 首个失败：无

## 组 3：计数边界、身份冲突、恢复事件与非触摸公开边界

- RED 命令：`$env:PYTHONPATH='电控/src'; python -m unittest discover -s '电控/tests/rpi' -p 'test_boundaries_and_public_api.py' -v`
- RED 退出码：`1`
- RED 用例数：`5`
- 首个失败：`TypeError: Scheduler.__init__() got an unexpected keyword argument 'initial_success_count_for_test'`
- GREEN 说明：移除测试专用初始化愿望接口，改用 255 件完整成功序列到达边界；未新增可绕过新轮验证的计数入口。
- GREEN 命令：同上
- GREEN 退出码：`0`
- GREEN 用例数：`5`
- 首个失败：无

## 验收边界

- `success_count` 直接复用协议 V0.4 `RoundSuccessCounter`。
- `FakeRenderer.present()` 只产生待处理对象；仅 `complete()` 产生 `RenderReceipt`。
- 本证据只证明离线骨架行为，不证明真实 HDMI 呈现、串口通信或硬件闭环。

## 审查修复：完成凭据不可仅按字段伪造

- 审查发现：原 `RenderReceipt` 仅校验四个公开字段；调用方可直接构造字段正确的实例，在未调用 `PendingRender.complete()` 时提前产生 ACK 意图。
- RED 命令：`$env:PYTHONPATH='电控/src'; python -m unittest '电控/tests/rpi/test_scheduler_rendering.py' -v`
- RED 退出码：`1`
- RED 用例数：`13`
- 首个失败：`RPI_RENDER_FORGE_001` 的 `SchedulerFault not raised`；其余 12 项通过。
- 最小修复：`PendingRender.complete()` 登记具体凭据对象的完成来源；调度器除字段/当前模型校验外，还要求收到同一已登记对象。仅字段相同的直接构造实例无完成来源，不能生成 ACK。
- GREEN 命令：同上
- GREEN 退出码：`0`
- GREEN 用例数：`13`
- 首个失败：无
- 保留语义：错件/旧模型凭据仍拒绝；同一真实凭据的重复通知仍复用唯一缓存意图；未加入真实显示、串口或物理参数。
