# 2026-08-20 挡板模块与指令清单验证记录

> 等级：L2（固件新增挡板控制模块）
> 结论：主机测试通过；未进行烧录与实机验证。

## 1. 本次改动

- 新增 `电控/firmware/stm32f407_m144z/App/Src/ec_barrier_test.c` 与 `App/Inc/ec_barrier_test.h`。
- `ec_board_stm32.c` 增加四路挡板 PWM 端口：PB0/TIM3_CH3、PB1/TIM3_CH4、PF6/TIM10_CH1、PF7/TIM11_CH1。
- `ec_diag.c` 增加 `PING`、`BARRIER ARM`、`BARRIER P<us>`、`BARRIER 1..4 P<us>`、`BARRIER COLLECT P<us>`、`BARRIER AVOID P<us>`、`BARRIER STOP`，`STATUS` 增加挡板字段。
- Keil 工程加入 `EC_BARRIER_TEST_BUILD=1` 与 `ec_barrier_test.c`。
- 新增指令清单 `docs/design/2026-08-20-motion-command-list-v1.md`。

## 2. 验证证据

因本机中文路径对 MinGW 编译不兼容，在 `%TEMP%` 纯英文目录复制源码后全新配置、构建并运行测试：

```text
ctest --output-on-failure
1/2 ec_firmware_host_tests    Passed
2/2 ec_diag_disabled_tests    Passed
```

测试覆盖：挡板授权、一次性授权、脉宽/通道范围、输入门禁、运行后停止、端口启动失败回退、与步进/舵机/组合互斥、指令解析与状态输出。

## 2.1 Keil 构建证据

用户在本机 Keil V5.06 重新构建：

```text
Program Size: Code=16416 RO-data=1700 RW-data=96 ZI-data=2576
"diankongv1.0\diankongv1.0" - 0 Error(s), 0 Warning(s).
Build Time Elapsed: 00:00:08
```

构建日志：`电控/firmware/stm32f407_m144z/MDK-ARM/barrier-command-v1-build.log`。

HEX：`电控/firmware/stm32f407_m144z/MDK-ARM/diankongv1.0/diankongv1.hex`

SHA256：`6C5C6A66725AFC191F87E9934E90B5DA1064B4E00FD5F6BFBEAE43E787959346`

> 注意：该 HEX 对应挡板版构建；XY 目标步数版源码随后已更新，需重新构建并重新记录哈希。

## 3. 未验证边界

- Keil HEX 由用户本机重建，本代理未在自身环境重复构建。
- 未实机接线、烧录或动作验证。
- 四路挡板的归集/避让脉宽未标定；固件只校验 500～2500 us，具体角度由上层配置传入。
- 挡板到位判据尚未建立，当前 `BARRIER COLLECT/AVOID` 只表示发出指定 PWM。
