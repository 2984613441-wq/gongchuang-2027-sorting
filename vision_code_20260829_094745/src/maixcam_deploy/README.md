# MaixCAM YOLO11 部署入口

运行于 MaixCAM 的 `main.py`，加载 MaixCAM 转换页生成的 YOLO11 `.mud`。

## 上传与运行

1. 把转换得到的 `model_xxxx.mud` 和 `model_xxxx.cvimodel` 传到设备同一目录，
   例如 `/root/my_models/`。
2. 把本目录 `main.py` 上传到设备，按需修改 `MODEL_PATH`。
3. 运行 `main.py`。

环境变量（可选）：

```text
MODEL_PATH=/root/my_models/model_8629.mud
CONF_TH=0.5
IOU_TH=0.45
REPORT_COMM=0
```

## 协议说明

`REPORT_COMM=0` 时只做屏幕显示和 stdout 诊断，不向外部发送数据。

`REPORT_COMM=1` 时使用 MaixHub 参考 `comm.CommProtocol` 上报
`APP_CMD_DETECT_RES=0x02`，payload 为每个目标的
`x,y,w,h,class_id,score`。该 payload 尚未与最终 STM32 指令契约对照，
启用前必须重新核对。
