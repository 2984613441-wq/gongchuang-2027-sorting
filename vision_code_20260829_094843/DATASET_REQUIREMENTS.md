# 视觉数据集要求（MaixHub 7 类形状检测）

> 用途：采集、整理、标注、上传 MaixHub 前的最小验收清单。
> 当前模型：MaixHub 在线路径为 YOLOv5s；本地训练后走 MaixCAM 转换推荐
> YOLO11n（备选 YOLOv8n、YOLOv5u）。两条路径输入均为 448×448，
> `contain` 等比缩放，`mean=0`、`std=255`。

## 硬性格式

- 上传 zip 内必须包含 `images/` 和 `xml/`（或 `annotations/`），Pascal VOC 格式。
- 一张图片对应一个同名 XML 标注文件。
- zip 不超过 500MB，图片总数不超过 3000 张。
- 7 个类别名固定为：

  ```text
  cube, cuboid, cylinder, hexagonal_prism,
  pentagonal_prism, square_pyramid, triangular_prism
  ```

- 上传时类别顺序不必手工固定，MaixHub 导出后会按上面顺序给出；
  仓库代码和 `data.yaml` 必须使用这个导出顺序。

## 数量与划分

- 当前 402 张不够，尤其 `cuboid` 只有 55 张。
- 总图量目标：**1000-1500 张**。
- 弱类最低要求：`cuboid`、`triangular_prism` 每类至少 150 张。
- 其他 5 类：每类至少 100 张。
- 蓝、灰两种颜色都要覆盖，避免模型按颜色分类。
- MaixHub 会自动抽 10% 验证集，总量到 1200 张后验证集约 120 张。
- 另留一份固定测试集 80-120 张，不上传 MaixHub，用于不同模型版本对比
  和实机抽查。

## 采集要求

- 尽量用真实 MaixCAM / GC4653 在比赛工位采集；用手机替代时，保持
  取景范围、距离、光照、背景和摆放位置一致。
- 源图分辨率不低于 448×448，画面清晰、目标完整、无运动模糊。
- 每个形状都要有俯视和斜视/侧视：只俯视时正方体和四角锥都接近方形，
  棱柱的棱线也容易丢。
- 每个形状做旋转、平移、不同距离和不同摆放角度。
- 建议每张图只放一个主目标，背景干净，避免多个物料互相遮挡。

## 标注要求

- 框必须完整包住整个几何体，不要只框局部。
- 在 448 输入下，目标框建议大于 100 像素；小于 10 像素的框会被平台忽略。
- 自动标注后必须人工抽查以下易混组合：

  ```text
  cube          vs square_pyramid
  cuboid        vs cube
  pentagonal_prism vs hexagonal_prism vs triangular_prism
  ```

- 对 `cuboid` 和 `triangular_prism` 这类弱类，人工复核比例应最高。

## 当前阻塞项

- 当前训练集 638 张（`训练1 (1).zip`，是旧 402 张的超集）。
- 每类图片数：`cuboid 94`、`triangular_prism 131`、`cube 98`、
  `square_pyramid 137`、`hexagonal_prism 181`、`pentagonal_prism 171`、
  `cylinder 130`。
- 仍低于目标：`cuboid` 和 `triangular_prism` 尚未到 150，`cube` 略低于 100。
- 这三个弱类需要优先补数据并人工核对标注，不能只靠继续增加总图量。

## 下一轮训练参数

- 输入：448×448，等比缩放。
- 随机镜像：开；随机旋转：开；随机模糊：开。
- 网络：本地迁移路径用 `yolo11n.pt`；备选 `yolov8n.pt` / `yolov5su.pt`。
  MaixHub 在线路径用 `yolov5s`。
  迭代 100-150；批数据量 32；最大学习率 0.001。
- 允许负样本：关闭；数据均衡：先关闭，弱类补齐后仍不达标再试。
