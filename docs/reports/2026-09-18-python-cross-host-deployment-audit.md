# Python 跨机部署与运行时来源审查（2026-09-18）

## 范围与限制

本记录只覆盖 Windows 工作区的源码/脚本/文档证据与可复核命令；本轮没有连接、上电、烧录或运行树莓派硬件，因此不宣称固件、串口、屏幕、电机或整机通过。

## 已核查证据

| 项目 | 证据 |
|---|---|
| 生产入口 | `电控/deploy/run_chain.py` 以 `from electrical_control...` 导入包，且说明依赖 `电控/src` 的 `PYTHONPATH`/`.pth`。 |
| 当前主机新版显示模块 | `电控/src/electrical_control/rpi/display_hdmi.py`：28,207 bytes、694 行、SHA-256 `989d5dff98d43cfedc3091ff7112b5f50738e565062d202d20a8314f1c860979`；`TwoStageDisplay`/`TwoStageInfo`/`load_font` 合计 20 处匹配；`_fit_into()` 使用 `getattr(Image, "Resampling", Image).LANCZOS`。 |
| 主机已有旧发布物 | `工具/pi_staging/ec-chain/src/electrical_control/rpi/display_hdmi.py`：8,799 bytes、213 行、SHA-256 `eae88e7a2aaa6a913bcf66a2edb59efa9d0fe1d25549523ea9c6394255385ff0`、上述符号 0 处；该副本仍有 `slots=True` 与直接 `Image.Resampling.LANCZOS`。 |
| 部署脚本行为 | `电控/deployment/deploy_to_pi.sh` 的 `FILES` 只有 `sorting_config.ini`、`quick_tune.sh`、`apply_config.py`，上传目标为 `/home/pi/`，不会更新 `run_chain.py` 或 `electrical_control`。 |
| 解释器/导入路径 | `电控/deploy/install.sh` 将源码写入 venv `.pth`；`电控/deploy/ec-chain.service` 又使用占位的 `/opt/ec-chain/src`、`/opt/ec-chain/deploy/run_chain.py`；旧桥接文档使用 `~/电控_src` + `~/电控_deploy`。 |
| 依赖 | `电控/deploy/requirements.txt` 为 `pyserial>=3.5`、`pillow>=9.0.0`，与已确认的树莓派 Pillow 8.1.2 不一致。 |
| 配置门禁 | 当前主机 `电控/deploy/sorting_config.ini` 只有 `Vision/Motion/Safety/Calibration/Network`，没有 `[DropPoints]`、`[BoxMap]` 或 `[TurntableAngles]`；当前 `run_chain.py` 真实模式会在策略加载时要求其中一套完整表。 |

## 用户已提供、尚未在本机复核的树莓派证据

树莓派存在 `/home/pi/电控/src/electrical_control`、`/home/pi/电控_src/electrical_control`、`/home/pi/电控_deploy/` 等副本；曾运行到 `/home/pi/电控/src/electrical_control/rpi/display_hdmi.py` 的 2026-09-09 旧版（约 215 行、3 个符号均为 0）。需按审查方案中的 `sys.path`、`__file__`、`python -v` 与进程 `/proc` 命令核实最终来源。

## 当前结论

最小可解释根因是发布物、入口路径、解释器/venv 和依赖没有被同一个版本标识绑定。主机工作区已经有能解释该现象的旧 staging 副本，但在树莓派上完成来源探针前，不能断言具体是哪一个副本被加载。NO-GO 结论成立。

## 工具

跨机清单脚本：`scripts/compare_deploy_trees.py`。默认跳过 `__pycache__`/测试缓存；以字节级 SHA-256、大小、文本行数、mtime(ns/UTC) 输出 CSV。缓存与 systemd 来源另按部署清单检查。
