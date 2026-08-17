# TASK-20260812-006：STM32 C 纯逻辑骨架

> **执行代理要求：** 实施时必须使用 `test-driven-development`；按本任务逐项执行可使用 `executing-plans`。先产生并保存真实 RED，再写最小生产代码，最后执行全量验收。  
> 日期：2026-08-12  
> 等级：L3，八项治理功能有限试行；不得宣称治理机制已正式验证或激活  
> 状态：任务设计已冻结，等待独立执行会话实施  
> 安全范围：只允许主机侧编译和纯 C 逻辑测试；禁止接线、上电、烧录、运动、采购和投板

## 1. 任务认知层

| 字段 | 当前记录 |
|---|---|
| 原始需求 | 第二批代码中建立 STM32 C 纯逻辑骨架，先验证 CRC32，再迁移可测试的状态机、有限去重和重启锁定规则。 |
| 表面问题 | 当前只有主机侧 Python 协议、状态机和 fake 驱动，没有可由 STM32 工程复用的 C 逻辑与主机 C 测试。 |
| 真正问题 | 在完整线协议和硬件参数均未冻结时，先证明跨语言 CRC 一致、安全状态迁移、一件一次、容量耗尽和重启后禁止续跑不会依赖 UART、HAL 或电机参数。 |
| 必须目标 | CRC-32/ISO-HDLC 已知向量通过；纯 C 状态机只消费领域事件并输出动作意图；固定容量去重不分配堆内存、不淘汰；启动即锁定旧上下文；主机 C 测试和现有 Python 55 项回归通过。 |
| 非必须目标 | 不实现统一外层帧、`ITEM_TASK` 完整 wire codec、CRC16、UART、DMA、GPIO、定时器、脉冲、回零算法、轨迹、真实 HAL、Flash 持久化或 Bootloader。 |
| 环境与资源限制 | Windows/PowerShell；当前可找到 CMake、CTest 和 GCC；共享工作区有其他编辑者；不得下载工具链，不得撤销、覆盖或格式化他人的修改。 |
| 主要风险 | 用 C 骨架暗中冻结未决线格式；无界缓存耗尽 RAM；重启后误把旧件当作可续跑；测试直接调用实现内部结构形成假绿。 |
| 节点能力建议 | Codex 负责 C 代码、主机测试和可执行验证；Claude 仅在实现完成后作只读复审。该路由是能力建议，不构成权力分配。 |
| 决策边界 | 用户已裁决“任一关键节点掉电或重启后锁定，禁止原轮次续跑，人工确认后重新自检、回零并开始新轮次”。缓存容量具体值依赖未来单轮最大件数，本任务只冻结“调用方显式提供容量、耗尽即锁定、不淘汰”。 |
| 当前阶段 | REVIEW-009 对主机侧 Python 逻辑有条件通过；STM32 C、实机显示闭环和硬件仍未验证。 |
| 验收方式 | 每组先观察 RED；GCC 主机编译开启严格告警；执行 C 测试、Python↔C CRC 对照、现有 55 项 Python 回归、禁写扫描和 `git diff --check`。 |

## 2. 事实、推断、观点与未知

### 2.1 已确认事实

- `docs/design/interface-contract.md` V0.4 冻结 `DISPLAY_ACK` 五字段规范字节序列：`target_seq + class_id + image_id + success_count + result_code`，五个字段均为 `u8`。
- 显示内容 CRC 使用 CRC-32/ISO-HDLC；输入 `01 02 03 04 05` 的结果是 `0x470B99F4`，载荷表示为大端字节 `47 0B 99 F4`。
- Python 状态机已经区分 `MOTION_DONE`、`ITEM_RESULT` 与首个有效 `DISPLAY_ACK`；前两者均不能独自放行下一件。
- REVIEW-009 实测协议 24、状态机 19、驱动 12，共 55 项通过，并将无界去重、掉电恢复和跨层测试列为开放 P1。
- 用户已经选择安全恢复规则：重启后不续跑旧轮；人工确认后重新自检、回零并建立新轮次。

### 2.2 本任务采用的推断与设计观点

- C 逻辑可通过“事件输入、动作意图输出”迁移 Python 安全语义，而不需要引用 STM32 HAL。该推断只能由主机 C 测试验证，不能外推为固件或硬件已验证。
- 因为本任务不实现持久化和跨节点恢复握手，最安全的启动语义是每次初始化都进入 `FAULT_LOCK/RESTART_CONTEXT_UNPROVEN`；不存在“恢复旧轮”入口。
- 固定容量去重采用调用方提供的静态存储；容量耗尽时返回显式错误并使状态机锁定。禁止 LRU、循环覆盖和静默丢弃，因为这些策略会使旧任务重新运动。
- 截止时间由外层监控器转换为 `DEADLINE_EXPIRED` 领域事件；C 纯逻辑层不读取时钟，也不定义毫秒、频率或定时器。

### 2.3 未知且不得补写为事实

- 完整 `ITEM_TASK` 载荷、X/Y/角度单位、有效值表达、端序与载荷长度。
- 统一帧头、外层 CRC16、最大帧长、波特率、心跳、超时和重传数值。
- 电机、A4988、GPIO、定时器、频率、脉冲宽度、速度、加速度、步数换算、电流、电压、细分、限位和回零参数。
- 单轮最大任务数。该未知项不阻塞接口和耗尽行为测试，但阻塞生产固件容量数值的最终冻结。

## 3. 八项治理功能

| 功能 | 本任务动作 |
|---|---|
| 文书 | 本文件记录目标、边界、接口、测试 ID、真实 RED/GREEN 填写位置和复审入口。 |
| 求是 | 区分事实、推断和未知；C 主机测试只证明纯逻辑，不写成 STM32 实机结论。 |
| 建制 | 建立 `CRC32 → 有限去重 → 领域状态机 → 动作意图` 单向依赖；板级代码不得进入本目录。 |
| 协同 | 执行者只拥有第 4 节目录；Claude 只读；共享工作区中不得撤销他人修改。 |
| 谏议 | 若实现需要 wire codec、HAL、计时数值或缓存淘汰，立即停止该部分并记录越界，不以候选默认值穿透门禁。 |
| 试行 | 仅 Windows 主机 GCC/CMake 测试；禁止板级编译、烧录、接线和运动。 |
| 审核 | 先逐项 TDD，再执行统一验收；Claude 输出新审查文件且不修改代码。 |
| 史官 | 保留 REVIEW-009 和全部 RED/GREEN 原始摘要；不得覆盖历史任务或审查记录。 |

独立性说明：Codex 主节点复核同体系执行结果时属于“弱独立性”；Claude 若未参与实现可作为另一节点只读复审，但因同属 AI 系统仍须记录其方法限制，不能等同实机或第三方认证。

## 4. 目录所有权与目标文件

本任务的实施者是以下目录的唯一写入者：

```text
电控/stm32_logic/
├── CMakeLists.txt
├── include/
│   ├── ec_crc32.h
│   ├── ec_dedup.h
│   └── ec_state_machine.h
├── src/
│   ├── ec_crc32.c
│   ├── ec_dedup.c
│   └── ec_state_machine.c
└── tests/
    ├── test_support.h
    ├── test_main.c
    ├── test_crc32.c
    ├── test_dedup.c
    ├── test_state_machine.c
    └── crc32_vector_cli.c
```

禁止修改：

- `电控/src/electrical_control/protocol/`
- `电控/src/electrical_control/state_machine/`
- `电控/src/electrical_control/drivers/`
- `电控/tests/protocol/`、`电控/tests/state_machine/`、`电控/tests/drivers/`
- 任何 STM32Cube、HAL、CMSIS、启动文件、链接脚本或板级工程
- 任何既有设计、任务、审查和经验文件；实现后的审核报告由主节点或 Claude 按明确所有权新建

所有执行者都不是仓库唯一编辑者。禁止使用会撤销他人工作的命令，禁止对范围外文件做全局格式化，禁止自行暂存或提交共享工作区中的其他修改。

## 5. 冻结的 C 逻辑接口

下列名称用于统一测试与实现；它们是逻辑 API，不是 wire codec，也不冻结外层字段宽度。

### 5.1 CRC32

```c
uint32_t ec_crc32_iso_hdlc(const uint8_t *data, size_t length);
```

- 以标准 CRC-32/ISO-HDLC 参数实现，不允许调用平台 CRC 外设或第三方库。
- 返回整数值；只有未来载荷编码层才负责把结果编码成 `47 0B 99 F4`。本任务不得实现外层帧。
- `length == 0` 时允许 `data == NULL`；`length > 0 && data == NULL` 属于调用契约错误，测试不得用未定义行为探测它。

### 5.2 固定容量去重

```c
typedef struct {
    uint32_t task_id;
    uint32_t frame_seq;
    uint32_t payload_fingerprint;
} ec_dedup_key_t;

typedef enum {
    EC_DEDUP_NEW = 0,
    EC_DEDUP_DUPLICATE,
    EC_DEDUP_CONFLICT,
    EC_DEDUP_FULL,
    EC_DEDUP_INVALID
} ec_dedup_result_t;

typedef struct ec_dedup_entry ec_dedup_entry_t;

typedef struct {
    ec_dedup_entry_t *entries;
    size_t capacity;
    size_t used;
} ec_dedup_t;

bool ec_dedup_init(ec_dedup_t *cache, ec_dedup_entry_t *storage, size_t capacity);
ec_dedup_result_t ec_dedup_observe(ec_dedup_t *cache, ec_dedup_key_t key);
void ec_dedup_clear_for_verified_new_round(ec_dedup_t *cache);
```

- `task_id/frame_seq` 的 `uint32_t` 仅是主机纯逻辑容器，不代表外层帧宽度或端序已冻结。
- 相同 `(task_id, frame_seq)` 且指纹相同返回 `DUPLICATE`；指纹不同返回 `CONFLICT`。
- 新身份在有空位时写入并返回 `NEW`；已满返回 `FULL`，不得覆盖、淘汰或修改已有记录。
- 存储由调用方提供；不得使用 `malloc/calloc/realloc/free`。
- 清空函数只能由已验证新轮次路径调用；普通重连、重传、超时和同轮恢复不得调用。

### 5.3 纯状态机

状态至少包含：

```text
FAULT_LOCK, POWER_ON, POST, HOMING, READY, PREPARE_BARRIER,
WAIT_TASK, VALIDATE_TASK, EXECUTING, WAIT_ITEM_RESULT,
WAIT_DISPLAY_ACK, COMPLETE
```

事件至少包含：

```text
MANUAL_NEW_ROUND_CONFIRMED, POST_PASSED, HOMING_PASSED,
BARRIER_AVOIDANCE_VERIFIED, ITEM_TASK_ACCEPTED,
TASK_SAFETY_VALIDATED, MOTION_DONE, ITEM_RESULT_RECORDED,
DISPLAY_ACK_VALIDATED, EMERGENCY_STOP, POWER_PERMISSION_LOST,
DEADLINE_EXPIRED, DEDUP_CAPACITY_EXHAUSTED
```

动作意图至少包含：

```text
STOP_ALL, DISABLE_DRIVERS, INHIBIT_POWER, BEGIN_POST,
BEGIN_HOMING, PREPARE_BARRIER, EMIT_BARRIER_READY,
START_MOTION, EMIT_MOTION_DONE, EMIT_ITEM_RESULT,
RESEND_CACHED_RESPONSE, REJECT_NEW_TASK
```

统一入口：

```c
void ec_sm_init(ec_state_machine_t *machine, ec_dedup_t *dedup);
ec_transition_t ec_sm_consume(ec_state_machine_t *machine, const ec_event_t *event);
```

接口不变量：

1. `ec_sm_init()` 每次都进入 `FAULT_LOCK`，故障原因为 `RESTART_CONTEXT_UNPROVEN`；返回/保存 `STOP_ALL | DISABLE_DRIVERS | INHIBIT_POWER` 意图。不存在恢复旧轮或恢复旧件 API。
2. `MANUAL_NEW_ROUND_CONFIRMED` 只有在 `round_closed && danger_area_clear && estop_released` 全真、且提供与旧轮不同的新轮标识时才允许清空去重、进入 `POWER_ON` 并请求重新 POST；不满足时保持锁定。
3. 回零只能在 POST 成功后开始；未完成 POST 和回零不得进入 `WAIT_TASK`。
4. 新任务必须先通过有限去重和显式安全验证；安全验证之前不得输出 `START_MOTION`。
5. 相同身份同载荷只输出缓存应答意图，不重复运动；相同身份异载荷或缓存满进入 `FAULT_LOCK`。
6. `MOTION_DONE` 只转入等待结果；`ITEM_RESULT_RECORDED` 只转入等待显示确认；只有首个已由上游完成内容校验的 `DISPLAY_ACK_VALIDATED` 才能离开本件并转入 `PREPARE_BARRIER`。
7. `DISPLAY_ACK_VALIDATED` 事件必须携带当前件逻辑身份；状态机不解析六字节 ACK，不计算 wire payload，不自行相信未验证 ACK。
8. 任一非锁定状态收到急停、执行器动力许可丢失、截止事件或去重容量耗尽，立即锁定并输出停止、禁驱和动力抑制意图；锁定后普通事件无效。
9. 本层不读取时钟；15 秒监测者属于未来适配层。重复消息、日志和重传不得被转换成可续时事件。
10. 成功数规则保留在已冻结的协议/上下文逻辑中。本状态机可携带本件结果和显示期望上下文，但不得建立第二套互相竞争的累计计数权威。

## 6. TDD 实施顺序与测试 ID

每组必须依次执行：写一个或一小组失败测试 → 运行并记录预期业务失败 → 写最小实现 → 运行通过 → 再重构。编译失败若来自缺少目标 API 可作为首个 RED；路径错误、编译器缺失或测试本身语法错误不能算业务 RED。

### 6.1 CRC32

| ID | 测试行为 | 通过条件 |
|---|---|---|
| `C-CRC-001` | 已知向量 `01 02 03 04 05` | 整数结果严格等于 `0x470B99F4` |
| `C-CRC-002` | 同一结果转换为四字节网络序 | 依次为 `47 0B 99 F4`；转换只写在测试/向量工具中，不扩成帧编码器 |
| `C-CRC-X-001` | Python 生产函数与 C 向量工具独立计算同一输入 | 两端打印相同的八位大写十六进制 `470B99F4` |

### 6.2 固定容量去重

| ID | 测试行为 | 通过条件 |
|---|---|---|
| `C-DEDUP-001` | 使用调用方提供的容量 2 存储，插入两个不同身份 | 两次均为 `NEW`，`used == 2` |
| `C-DEDUP-002` | 重复观察同身份同指纹 | 返回 `DUPLICATE`，`used` 不变 |
| `C-DEDUP-003` | 同身份不同指纹 | 返回 `CONFLICT`，原条目不变 |
| `C-DEDUP-004` | 满载后插入第三个身份 | 返回 `FULL`，前两个条目仍可识别，未发生淘汰 |
| `C-DEDUP-005` | 初始化参数为空或容量为 0 | 明确失败，不分配堆内存、不越界 |
| `C-DEDUP-006` | 经验证新轮次清空 | `used == 0`；随后原身份作为新轮上下文可被重新登记 |

容量 2 只用于构造耗尽测试，不是固件生产容量裁决。

### 6.3 重启与人工新轮门禁

| ID | 测试行为 | 通过条件 |
|---|---|---|
| `C-SM-BOOT-001` | 新建状态机 | 初态为 `FAULT_LOCK/RESTART_CONTEXT_UNPROVEN`，包含三项安全动作意图 |
| `C-SM-BOOT-002` | 锁定后输入旧任务、运动完成或 ACK | 状态不变且不得出现 `START_MOTION` |
| `C-SM-RESET-001` | 人工确认条件任一为假 | 保持锁定，缓存不清空 |
| `C-SM-RESET-002` | 三个条件全真但新轮标识与旧轮相同 | 保持锁定，缓存不清空 |
| `C-SM-RESET-003` | 条件全真且为不同新轮 | 清空旧缓存，进入重新 POST 路径；仍未运动 |
| `C-SM-RESET-004` | 新轮 POST 后未回零或回零失败 | 不得进入接件状态 |

### 6.4 一件一次与逐件门禁

| ID | 测试行为 | 通过条件 |
|---|---|---|
| `C-SM-GATE-001` | 合法任务进入后尚未安全验证 | 不输出 `START_MOTION` |
| `C-SM-GATE-002` | 当前任务安全验证通过 | 恰好输出一次 `START_MOTION` |
| `C-SM-ONCE-001` | 重复同身份同载荷 | 仅缓存应答，不产生第二次运动 |
| `C-SM-ONCE-002` | 同身份异载荷 | 进入 `FAULT_LOCK`，不产生新运动 |
| `C-SM-EVENT-001` | 只收到 `MOTION_DONE` | 进入 `WAIT_ITEM_RESULT`，不放行下一件 |
| `C-SM-EVENT-002` | 收到成功或失败结果 | 均进入 `WAIT_DISPLAY_ACK`，不放行下一件 |
| `C-SM-ACK-001` | ACK 身份不匹配或未标记为已验证 | 保持等待，不清除当前件 |
| `C-SM-ACK-002` | 首个匹配且已验证 ACK | 转入 `PREPARE_BARRIER`；还需挡板避让验证后才回到 `WAIT_TASK` |
| `C-SM-ACK-003` | 重复已消费 ACK | 不二次放行、不改变本轮成功计数语义 |
| `C-SM-CAP-001` | 去重缓存返回 `FULL` | 立即锁定且不淘汰、不启动新任务 |

### 6.5 全局安全事件

| ID | 测试行为 | 通过条件 |
|---|---|---|
| `C-SM-ESTOP-001` | 每个非锁定状态收到急停 | 进入锁定并产生三项安全意图 |
| `C-SM-POWER-001` | 活动状态动力许可丢失 | 进入锁定并产生三项安全意图 |
| `C-SM-TIME-001` | 活动状态收到 `DEADLINE_EXPIRED` | 在处理后续任务/进度/ACK前锁定 |
| `C-SM-LOCK-001` | 已锁定后重复安全事件和普通事件 | 安全动作不被撤销，不产生运动 |

## 7. 精确实施步骤

### 阶段 A：建立可执行测试壳

- [ ] 创建第 4 节目录和 `CMakeLists.txt`；只配置 C11 主机静态库、`ec_logic_tests` 和 `crc32_vector_cli`。
- [ ] GCC/MinGW 启用 `-std=c11 -Wall -Wextra -Wpedantic -Werror`；MSVC 不是本轮验收工具链，不写其专用兼容分支。
- [ ] `test_support.h` 提供最小断言和失败计数；`test_main.c` 显式调用三个测试文件的注册函数，最终打印 `ALL STM32 LOGIC TESTS PASSED` 或非零退出。
- [ ] 先只声明测试预期而不创建生产实现，运行构建并记录因缺少 API 的真实 RED。

### 阶段 B：CRC32 RED→GREEN

- [ ] 先写 `C-CRC-001/002`，运行并保留失败摘要。
- [ ] 添加 `ec_crc32.h/.c` 的最小逐字节实现，不引入查表生成器、平台 CRC 或外部依赖。
- [ ] 构建向量 CLI；它只对固定五字节向量输出一行 `470B99F4`。
- [ ] 执行 Python↔C 对照；差异即失败，不允许修改向量迎合实现。

### 阶段 C：有限去重 RED→GREEN

- [ ] 先写 `C-DEDUP-001..006` 并运行 RED。
- [ ] 实现调用方存储、线性查找和显式满载结果。当前规模未知，不引入哈希、LRU 或动态内存。
- [ ] 扫描 `malloc|calloc|realloc|free`；生产 C 源命中即失败。

### 阶段 D：纯状态机 RED→GREEN

- [ ] 先完成重启和人工新轮测试 `C-SM-BOOT-*`、`C-SM-RESET-*`，观察 RED 后实现最小启动锁定路径。
- [ ] 再完成一件一次和门禁测试，观察 RED 后实现正常主链。
- [ ] 最后完成全局安全事件矩阵，观察至少一个新增失败，再实现统一的高优先级故障入口。
- [ ] 重构时保持状态、事件、动作意图为显式枚举；不得把 GPIO、计时或串口回调塞入 `ec_sm_consume()`。

### 阶段 E：回归与证据

- [ ] 新鲜构建并执行所有 C 测试。
- [ ] 新鲜执行 Python↔C CRC 对照。
- [ ] 新鲜执行现有协议、状态机和驱动 55 项回归。
- [ ] 执行范围扫描、差异检查并记录退出状态。
- [ ] 只报告实际测试数；测试框架若未逐项打印，则同时报告上表 ID 数和可执行程序退出码，不把断言数伪称用例数。

## 8. 验收命令

从仓库根目录 `C:\Users\29845\Desktop\工创赛` 执行。不得下载依赖。

### 8.1 工具链存在性

```powershell
Get-Command cmake, ctest, gcc | Select-Object Name, Source
```

预期：三项均可解析；任一缺失则记录“主机 C 验证阻塞”，不得改用板级编译或联网安装。

### 8.2 C 配置、严格编译与测试

```powershell
cmake -S '电控/stm32_logic' -B '电控/stm32_logic/build' -G 'MinGW Makefiles' -DCMAKE_BUILD_TYPE=Debug
cmake --build '电控/stm32_logic/build' --clean-first
ctest --test-dir '电控/stm32_logic/build' --output-on-failure
```

预期：三条命令退出 0；严格告警下无 warning；CTest 报告 100% tests passed。

### 8.3 Python↔C CRC 对照

```powershell
$env:PYTHONPATH = (Resolve-Path '电控/src').Path
$pythonCrc = python -c "from electrical_control.protocol import crc32_iso_hdlc; print(format(crc32_iso_hdlc(bytes([1,2,3,4,5])), '08X'))"
$cCrc = & '电控/stm32_logic/build/crc32_vector_cli.exe'
if ($pythonCrc -ne '470B99F4' -or $cCrc -ne $pythonCrc) { throw "CRC mismatch: Python=$pythonCrc C=$cCrc" }
"CRC_MATCH=$cCrc"
```

预期：退出 0，最后一行严格为 `CRC_MATCH=470B99F4`。

### 8.4 现有 55 项 Python 回归

```powershell
$env:PYTHONPATH = (Resolve-Path '电控/src').Path
python -m unittest discover -s '电控/tests/protocol' -p 'test_*.py' -v
python -m unittest discover -s '电控/tests/state_machine' -p 'test_*.py' -v
python -m unittest discover -s '电控/tests/drivers' -p 'test_*.py' -v
```

基线预期：协议 24、状态机 19、驱动 12，合计 55 项，0 failure、0 error。若共享工作区后来合法增加测试，应以实际更多数量为准，但不得少于该基线。

### 8.5 越界和动态内存扫描

```powershell
$sourceFiles = Get-ChildItem '电控/stm32_logic/include','电控/stm32_logic/src' -Recurse -File
$forbidden = $sourceFiles | Select-String -Pattern 'malloc|calloc|realloc|free|HAL_|GPIO|UART|USART|DMA|TIM[0-9]|A4988|baud|steps_per_mm|pulse_width|acceleration'
if ($forbidden) { $forbidden; throw 'Forbidden STM32 logic binding found' }
```

预期：0 命中、退出 0。注释中若必须说明禁项，应放在本任务文件，不写进生产 C 代码，以避免扫描歧义。

### 8.6 差异检查与所有权核对

```powershell
git diff --check
git status --short
```

预期：`git diff --check` 退出 0。实施者逐项确认自己只修改 `电控/stm32_logic/`；工作区其他差异归其他编辑者所有，不得清理。

## 9. RED/GREEN 史官记录格式

实施会话必须在交接报告中填写，不得预填“通过”：

| 阶段 | 首个 RED 命令 | 真实失败原因与退出码 | GREEN 命令 | 实际通过数与退出码 |
|---|---|---|---|---|
| CRC32 | 8.2 | 实施后填写 | 8.2 | 实施后填写 |
| 有限去重 | 8.2 | 实施后填写 | 8.2 | 实施后填写 |
| 重启锁定 | 8.2 | 实施后填写 | 8.2 | 实施后填写 |
| 主链状态机 | 8.2 | 实施后填写 | 8.2 | 实施后填写 |
| 全局安全 | 8.2 | 实施后填写 | 8.2 | 实施后填写 |
| 全量验收 | 8.2–8.6 | 不适用 | 8.2–8.6 | 实施后填写 |

“实施后填写”是执行证据字段，不是允许省略的功能占位；如果某阶段未实际观察 RED，必须如实标注 TDD 证据缺失，不能补造历史。

## 10. 完成门禁

只有同时满足下列条件，才可裁决“STM32 C 纯逻辑骨架主机侧有条件通过”：

- `C-CRC-*`、`C-DEDUP-*`、`C-SM-*` 全部通过，且保留可核验 RED→GREEN 摘要。
- C 与 Python 对 `01 02 03 04 05` 均得 `0x470B99F4`。
- 去重无动态内存、无淘汰；容量耗尽会故障锁定。
- 每次初始化都锁定旧上下文；不存在旧轮自动续跑入口；人工确认后仍必须重新 POST 和回零。
- 急停、动力许可丢失、截止事件在所有适用状态优先锁定。
- 现有 Python 55 项基线不回归；禁写扫描和 `git diff --check` 通过。
- Claude 完成第 11 节只读复审，Codex 对其发现逐项形成采纳、驳回或待确认对账。

即使全部通过，也仍然禁止：采购、接线、上电、烧录、实机运动。它不冻结完整线协议，不证明 STM32 工具链、Flash/RAM 占用、真实中断并发、真实计时、HAL、驱动器、电机、限位、急停电路或显示闭环。

## 11. Claude 只读复审入口

实现完成并由主 Codex 新鲜复跑第 8 节后，将以下提示词交给 Claude：

```text
请对工创赛“STM32 C纯逻辑骨架”执行L3只读复审。工作区：
C:\Users\29845\Desktop\工创赛

完整读取：
1. 当前AGENTS.md治理指令与CLAUDE.md
2. docs/requirements/analysis.md
3. docs/design/interface-contract.md V0.4
4. docs/design/stm32-state-machine-pseudocode.md
5. docs/superpowers/plans/2026-08-12-second-batch-parallel-development.md
6. .claude/tasks/TASK-20260812-006-stm32-c-logic-skeleton.md
7. .claude/reviews/REVIEW-20260812-009-claude-enhanced-a-v04-comprehensive-review.md
8. 电控/src/electrical_control/protocol/、state_machine/及其测试（只读对照）
9. 电控/stm32_logic/全部生产代码、测试与构建配置

这是只读审查。不得修改任何生产代码、测试、设计、任务或历史审查文件。
把新报告写入：
.claude/reviews/REVIEW-20260812-010-claude-second-batch-readonly-review.md

必须独立复跑任务书第8节可执行命令，并重点检查：
- CRC-32/ISO-HDLC是否独立得到01 02 03 04 05 → 0x470B99F4，是否错误缩减五字段范围；
- C接口是否暗中冻结ITEM_TASK完整wire格式、外层帧、CRC16或物理参数；
- 去重是否真正固定容量、调用方存储、无动态分配、无淘汰；FULL或CONFLICT是否锁定且不运动；
- 每次初始化是否都以RESTART_CONTEXT_UNPROVEN锁定，是否存在任何旧轮/旧件自动续跑路径；
- 人工新轮是否要求旧轮关闭、危险区清空、急停释放且新轮标识不同，之后是否强制POST和回零；
- 安全事件是否先于普通事件处理，MOTION_DONE/ITEM_RESULT/错误ACK是否可能提前放行；
- C层是否读取时钟或包含UART、GPIO、定时器、频率、电机、A4988等未冻结参数；
- 测试是否覆盖反例，RED/GREEN证据是否真实，Python 55项是否回归；
- C主机测试结论是否被错误表述成固件、硬件或实机验证。

报告按：总体裁决、审查独立性及限制、八项治理、事实/推断/未知、测试复现、P0/P1/P2、采纳/驳回/待确认、越权扫描、实机前门禁输出。若无法做到真正独立，明确标注弱独立性。不得声称硬件已验证。
```

## 12. 交接结论

本任务书只授权创建和验证 `电控/stm32_logic/` 的主机侧纯 C 逻辑。最小验证顺序是：CRC已知向量 → 有限去重 → 启动锁定/人工新轮 → 正常逐件状态机 → 全局安全事件 → Python回归 → Claude只读复审。任何需要 wire codec、硬件参数、真实计时或持久化恢复的实现请求都超出本任务，必须返回主节点重新裁决。
