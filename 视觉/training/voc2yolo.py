# -*- coding: utf-8 -*-
"""
VOC 格式 -> YOLO 格式转换 + train/val 划分 + 生成 data.yaml
输入: D:/AAAdesktop1/shijue/voc_export_638/  (images/*.jpg, annotations/*.xml, train.txt)
输出: D:/AAAdesktop1/shijue/yolo_dataset/    (images|labels/{train,val}, data.yaml)
"""
import os
import shutil
import random
import xml.etree.ElementTree as ET

SRC = r"D:/AAAdesktop1/shijue/voc_export_638"
DST = r"D:/AAAdesktop1/shijue/yolo_dataset"

# 类别顺序必须与训练/部署一致（来自 数据集1.0/labels_raw/classes.txt）
CLASSES = [
    "cube", "cuboid", "cylinder", "hexagonal_prism",
    "pentagonal_prism", "square_pyramid", "triangular_prism",
]
CLASS2ID = {name: i for i, name in enumerate(CLASSES)}

VAL_RATIO = 0.2
SEED = 42


def parse_xml(xml_path):
    """返回 (class_ids, boxes) 其中 boxes 为 YOLO 归一化 [cx, cy, w, h]"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    size = root.find("size")
    width = float(size.find("width").text)
    height = float(size.find("height").text)
    boxes = []
    class_ids = []
    for obj in root.findall("object"):
        name = obj.find("name").text.strip()
        if name not in CLASS2ID:
            raise ValueError(f"未知类别: {name!r} in {xml_path}")
        bnd = obj.find("bndbox")
        xmin = float(bnd.find("xmin").text)
        ymin = float(bnd.find("ymin").text)
        xmax = float(bnd.find("xmax").text)
        ymax = float(bnd.find("ymax").text)
        cx = (xmin + xmax) / 2.0 / width
        cy = (ymin + ymax) / 2.0 / height
        w = (xmax - xmin) / width
        h = (ymax - ymin) / height
        class_ids.append(CLASS2ID[name])
        boxes.append((cx, cy, w, h))
    return class_ids, boxes


def main():
    ann_dir = os.path.join(SRC, "annotations")
    img_dir = os.path.join(SRC, "images")
    xml_files = sorted(f for f in os.listdir(ann_dir) if f.endswith(".xml"))

    # 建立 图片文件 -> xml 的映射（图片与 xml 同 stem）
    items = []
    for xf in xml_files:
        stem = os.path.splitext(xf)[0]
        # 找同名图片（扩展名可能是 jpg/jpeg/png）
        img_file = None
        for ext in (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"):
            if os.path.exists(os.path.join(img_dir, stem + ext)):
                img_file = stem + ext
                break
        if img_file is None:
            raise FileNotFoundError(f"找不到 {stem} 对应的图片")
        items.append((stem, img_file, xf))

    print(f"共找到 {len(items)} 个标注样本")

    random.seed(SEED)
    random.shuffle(items)
    n_val = int(len(items) * VAL_RATIO)
    val_items = items[:n_val]
    train_items = items[n_val:]
    print(f"train={len(train_items)}  val={len(val_items)}")

    # 转换并写标签
    stats = {"train": {k: 0 for k in range(len(CLASSES))},
             "val": {k: 0 for k in range(len(CLASSES))}}
    box_total = {"train": 0, "val": 0}

    for split, subset in (("train", train_items), ("val", val_items)):
        os.makedirs(os.path.join(DST, "images", split), exist_ok=True)
        os.makedirs(os.path.join(DST, "labels", split), exist_ok=True)
        for stem, img_file, xf in subset:
            class_ids, boxes = parse_xml(os.path.join(ann_dir, xf))
            # 复制图片
            shutil.copy2(os.path.join(img_dir, img_file),
                         os.path.join(DST, "images", split, img_file))
            # 写标签
            lbl_path = os.path.join(DST, "labels", split, stem + ".txt")
            with open(lbl_path, "w", encoding="utf-8") as f:
                for cid, (cx, cy, w, h) in zip(class_ids, boxes):
                    f.write(f"{cid} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")
                    stats[split][cid] += 1
                    box_total[split] += 1

    # 生成 data.yaml
    yaml_path = os.path.join(DST, "data.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write("# 工创赛 7 类三维几何体检测\n")
        f.write(f"path: {DST}\n")
        f.write("train: images/train\n")
        f.write("val: images/val\n")
        f.write("\nnc: %d\n" % len(CLASSES))
        f.write("names:\n")
        for i, name in enumerate(CLASSES):
            f.write(f"  {i}: {name}\n")

    # 打印统计
    print("\n=== 类别分布（框数）===")
    print(f"{'class':<18}{'train':>7}{'val':>7}{'合计':>7}")
    for i, name in enumerate(CLASSES):
        t = stats["train"][i]
        v = stats["val"][i]
        print(f"{name:<18}{t:>7}{v:>7}{t+v:>7}")
    print(f"{'TOTAL':<18}{box_total['train']:>7}{box_total['val']:>7}{box_total['train']+box_total['val']:>7}")
    print(f"\n完成。data.yaml -> {yaml_path}")


if __name__ == "__main__":
    main()
