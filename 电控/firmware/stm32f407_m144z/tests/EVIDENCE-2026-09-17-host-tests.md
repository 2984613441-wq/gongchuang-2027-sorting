# 主机侧测试恢复 + ACK 回归：实测证据（2026-09-17）

本文件只记录**真实执行过的命令与原文输出**，不含复述成分。
工作目录：`C:\\Users\\29845\\Desktop\\工创赛`；工具链：gcc 16.1.0 (MinGW-W64 UCRT)、
CMake 4.4.0、Ninja 1.13.2、mingw32-make、pytest 9.1.1 (`py -3`)。

---

## 0. 中文路径问题：两次尝试与结论

### 尝试 1（失败）：直接在中文路径下用 Ninja

```
$ cd "电控/firmware/stm32f407_m144z/tests" && cmake -S . -B build-verify -G Ninja -DCMAKE_BUILD_TYPE=Release
-- Configuring done (1.4s)
-- Generating done (0.1s)
-- Build files have been written to: C:/Users/29845/Desktop/工创赛/电控/firmware/stm32f407_m144z/tests/build-verify

$ cmake --build build-verify
[9/40] Building C object .../C_/Users/29845/Desktop/������/���/firmware/stm32f407_m144z/App/Src/ec_servo_test.c.obj
FAILED: CMakeFiles/ec_firmware_host_tests.dir/C_/Users/29845/Desktop/������/���/firmware/stm32f407_m144z/App/Src/ec_servo_test.c.obj
Assembler messages:
Fatal error: can't create CMakeFiles/ec_firmware_host_tests.dir/C_/Users/29845/Desktop/������/���/firmware/stm32f407_m144z/App/Src/ec_servo_test.c.obj: No such file or directory
...
ninja: build stopped: subcommand failed.
BUILD_EXIT=1
```

原因：目标文件路径里内嵌了源码绝对路径，中文被 ANSI/UTF-8 双重转码成乱码目录名，ninja 建不出该目录。

### 尝试 2（成功）：`subst S:` 映射 + **MinGW Makefiles** 生成器

```
$ cmd //c "subst S: C:\Users\29845\Desktop\工创赛\电控"
$ subst
S:\: => C:\Users\29845\Desktop\������\���
```

Ninja 生成器在 S: 盘下首次构建能成功，但**第二次构建必定失败**（已复现）：

```
$ ninja            # 紧接在一次成功的完整构建之后
ninja: error: FindFirstFileExA(C:/Users/29845/Desktop/工创赛/电控/stm32_logic/include): The filename, directory name, or volume label syntax is incorrect.
E1_EXIT=1
```

`.ninja_deps` 里存了 gcc 依赖文件解析后的**真实中文路径**（`grep -ac Desktop .ninja_deps` → `4`）；
删掉 `.ninja_deps` 后同一目录可再次完整构建成功（40/40 链接通过）。这是 ninja 1.13.2 的
A 版 Win32 API 处理非 ASCII 路径的问题，不是测试代码问题。

**因此结论：本机可复现的配方是 `subst S:` + `-G "MinGW Makefiles"`。**（CMake/Ninja 的历史
`build-gcc` 目录同样受此影响。）

---

## 1. stm32_logic 主机测试（CMake + MinGW Makefiles + ctest）

```
$ cmake -S S:/stm32_logic -B S:/stm32_logic/build-make -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
-- Configuring done (0.1s)
-- Generating done (0.1s)
-- Build files have been written to: S:/stm32_logic/build-make

$ cmake --build S:/stm32_logic/build-make
[ 76%] Built target ec_logic_tests
[ 88%] Built target crc32_vector_cli
[100%] Built target item_task_vector_cli

$ cd S:/stm32_logic/build-make && ctest --output-on-failure
Test project S:/stm32_logic/build-make
    Start 1: ec_logic_tests
1/1 Test #1: ec_logic_tests ...................   Passed    0.01 sec

100% tests passed out of 1

Total Test time (real) =   0.02 sec
```

首次完整构建（17/17 目标，含 `libec_stm32_logic.a`、三个可执行文件）与逐条用例输出：

```
RUN C-CRC-001 ... RUN P-NACK-001
RUN C-GW-BOOT-001 ... RUN C-GW-PICK-004
ALL 77 STM32 LOGIC TESTS PASSED
ec_logic_tests EXIT=0
```

## 2. 固件主机测试（CMake + MinGW Makefiles + ctest，5 个 target）

```
$ cmake -S S:/firmware/stm32f407_m144z/tests -B S:/firmware/stm32f407_m144z/tests/build-make -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
-- Configuring done (0.1s)
-- Generating done (0.2s)
-- Build files have been written to: S:/firmware/stm32f407_m144z/tests/build-make

$ cmake --build S:/firmware/stm32f407_m144z/tests/build-make
[ 82%] Built target ec_axis_driver_tests
[ 92%] Built target ec_motion_plan_tests
[100%] Built target ec_demo_tests
（首次完整构建 40/40：编译 35 个 .obj + 链接 5 个可执行文件，BUILD_EXIT=0）

$ cd S:/firmware/stm32f407_m144z/tests/build-make && ctest --output-on-failure
Test project S:/firmware/stm32f407_m144z/tests/build-make
    Start 1: ec_firmware_host_tests
1/5 Test #1: ec_firmware_host_tests ...........   Passed    0.01 sec
    Start 2: ec_diag_disabled_tests
2/5 Test #2: ec_diag_disabled_tests ...........   Passed    0.01 sec
    Start 3: ec_axis_driver_tests
3/5 Test #3: ec_axis_driver_tests .............   Passed    0.01 sec
    Start 4: ec_motion_plan_tests
4/5 Test #4: ec_motion_plan_tests .............   Passed    0.01 sec
    Start 5: ec_demo_tests
5/5 Test #5: ec_demo_tests ....................   Passed    0.01 sec

100% tests passed out of 5

Total Test time (real) =   0.07 sec

$ ./ec_firmware_host_tests.exe
ALL FIRMWARE HOST TESTS PASSED
exit=0

$ ./ec_motion_plan_tests.exe
ALL MOTION PLAN HOST TESTS PASSED
exit=0
```

---

## 3. ACK 回归用例：修复前（红）实测

在 `.tmp-ack-red/`（仓库内临时副本，**未改动仓库 src**）中删掉 `ec_app.c:268` 的那一行
`ec_app_flush_tx();`，用同一套测试重新构建运行。三个用例逐个暴露（前面的用例断言被临时
中性化，只为让后面的用例跑到自己的断言）：

```
===== VARIANT A: all three ACK tests enabled =====
T:/firmware/stm32f407_m144z/tests/test_app.c:440 assertion failed:
    tx_count(EC_CMD_ACK, EC_ACK_REASON_ACCEPTED, 1U) == 1U      EXIT=1

===== VARIANT B: test 1 assertions neutered =====
T:/firmware/stm32f407_m144z/tests/test_app.c:455 assertion failed:
    tx_count(EC_CMD_ACK, EC_ACK_REASON_ACCEPTED, 1U) == 1U      EXIT=1
（同用例的 459 行"ACK 恰好一次"同样会红）

===== VARIANT C: test 1+2 assertions neutered =====
T:/firmware/stm32f407_m144z/tests/test_app.c:479 assertion failed: first != NULL   EXIT=1
```

修复后（仓库现状）同三个用例必绿：见第 2 节 `ALL FIRMWARE HOST TESTS PASSED`。

### 反向验证（把 flush 语义钉死）

在副本里保留 `ec_app.c:268` 的修复、只删掉网关入口的两处 `g->tx_len = 0U;`
（`ec_protocol_gateway.c:375` feed_byte 入口、`:446` inject 入口）：

```
=========================== MUTATION DIAG ===========================
MUTATION-DIAG ACK(ACCEPTED,seq=1) x3 total_decoded_frames=28 END
T:/firmware/stm32f407_m144z/tests/test_app.c:455 assertion failed:
    tx_count(EC_CMD_ACK, EC_ACK_REASON_ACCEPTED, 1U) == 1U      EXIT=1
```

即：一帧 22 字节的 ITEM_TASK 打出 **3 个 ACK、28 帧**——重发风暴确实存在，用例 2 抓得住。

---

## 4. Python 主机测试

```
$ cd 电控 && PYTHONPATH=src py -3 -m pytest tests -q -p no:cacheprovider
2 failed, 258 passed, 54 subtests passed in 0.40s
FAILED tests/rpi/test_socket_vision_source.py::test_matching_task_id_yields_serializable_context
FAILED tests/rpi/test_socket_vision_source.py::test_single_slot_latest_batch_overwrites_stale

$ cd 视觉 && PYTHONPATH=. py -3 -m pytest tests -q -p no:cacheprovider
75 passed, 8 subtests passed in 0.22s
```

注：不加 `PYTHONPATH=src` 时 24 个测试文件全部 collection error（`ModuleNotFoundError: No module named 'electrical_control'`）。

上述 2 个失败**不是本次恢复造成的**：把归档副本
`archive/tests-2026-09-15/电控-python-tests/rpi/test_socket_vision_source.py` 直接拿来跑，
同样是这 2 个用例红：

```
2 failed, 4 passed in 0.18s
FAILED ...test_socket_vision_source.py::test_matching_task_id_yields_serializable_context
FAILED ...test_socket_vision_source.py::test_single_slot_latest_batch_overwrites_stale
```

根因（属 src 侧设计缺口，未改）：`BATCH_TARGETS` 每个 target 7 字节里没有颜色/box_id 字段，
`parse_batch_targets()` 造不出 `box_id`，`SocketVisionSource._expand()` 按"缺 box_id 即拒识"
fail-closed 丢弃 —— wire 路径今天一件也产不出来。这两个用例断言 wire 路径必须产出，故结构性红。
修复要么把 box_id 放上 wire（协议变更），要么把用例改成走 `_expand()`（测试自身声明是"已知红灯"，
本次不动）。

---

## 5. 复现命令（照抄即可）

```bash
cmd //c "subst S: C:\Users\29845\Desktop\工创赛\电控"
cmake -S S:/stm32_logic -B S:/stm32_logic/build-make -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
cmake --build S:/stm32_logic/build-make
(cd S:/stm32_logic/build-make && ctest --output-on-failure)

cmake -S S:/firmware/stm32f407_m144z/tests -B S:/firmware/stm32f407_m144z/tests/build-make -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
cmake --build S:/firmware/stm32f407_m144z/tests/build-make
(cd S:/firmware/stm32f407_m144z/tests/build-make && ctest --output-on-failure)

# Python 主机测试
(cd 电控 && PYTHONPATH=src py -3 -m pytest tests -q -p no:cacheprovider)
(cd 视觉 && PYTHONPATH=.  py -3 -m pytest tests -q -p no:cacheprovider)

# 撤掉盘符映射
cmd //c "subst S: /D"
```
