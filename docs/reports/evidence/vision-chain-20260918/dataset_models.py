"""Read-only audit of existing dataset labels and ONNX assets; no inference or hardware.

Run from the repository: py -3 -X utf8 docs/reports/evidence/vision-chain-20260918/dataset_models.py
All production and D: paths are read only. The caller may redirect stdout to evidence.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[4]
PRE = ROOT / "视觉/datasets/preliminary"
WS = ROOT / "workspace_label"
EXTERNAL = Path(r"D:\AAAdesktop1\shijue")
CURRENT = EXTERNAL / "yolo_dataset"
VOC = EXTERNAL / "voc_export_638"
ROUND3 = EXTERNAL / "ultralytics-8.3.163/datasets/block_dataset_v1_7class_round3"
CLASSES = ("cube", "cuboid", "cylinder", "hexagonal_prism", "pentagonal_prism", "square_pyramid", "triangular_prism")
REMAP = {0: 3, 1: 6, 2: 4, 3: 2, 4: 5, 5: 1, 6: 0}


def emit(kind, **values):
    print(kind + " " + json.dumps(values, ensure_ascii=False, sort_keys=True))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def label(path):
    return [(int(p[0]), tuple(round(float(x), 6) for x in p[1:]))
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if (p := line.split())]


def label_stats(directory, pattern="*.txt"):
    files = sorted(p for p in directory.glob(pattern) if p.name not in ("classes.txt", "class.txt"))
    counts = Counter()
    empty = 0
    bad = []
    digest = hashlib.sha256()
    for p in files:
        digest.update(p.relative_to(directory).as_posix().encode())
        digest.update(p.read_bytes())
        rows = label(p)
        empty += not rows
        for index, (class_id, box) in enumerate(rows, 1):
            counts[class_id] += 1
            if class_id not in range(7) or len(box) != 4 or not all(0 <= x <= 1 for x in box):
                bad.append(f"{p}:{index}")
    emit("LABEL_STATS", path=str(directory), file_count=len(files), empty_files=empty,
         counts=dict(sorted(counts.items())), boxes=sum(counts.values()), invalid_rows=bad,
         sha256_names_and_contents=digest.hexdigest())
    return files


def text_file(path):
    if not path.is_file():
        emit("TEXT_MISSING", path=str(path))
        return
    emit("TEXT_FILE", path=str(path), sha256=sha(path))
    for number, line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
        print(f"{path}:{number}: {line}")


def image_index(paths):
    index = defaultdict(list)
    for p in sorted(paths):
        index[sha(p)].append(p)
    return index


def classify(left, right):
    """Compare labels on byte-identical images, preserving all boxes/multiplicity."""
    if Counter(left) == Counter(right):
        return "same"
    if Counter((REMAP.get(c, c), b) for c, b in left) == Counter(right):
        return "old_to_new_remap_exact"
    if Counter(b for _, b in left) == Counter(b for _, b in right):
        return "same_boxes_other_class_mismatch"
    return "different_box_annotations"


def compare_images(left_root, left_images, right_index, left_label, right_label, name):
    counts = Counter()
    examples = defaultdict(list)
    for image_path in sorted(left_images):
        image_hash = sha(image_path)
        matches = right_index.get(image_hash, [])
        if not matches:
            counts["no_byte_identical_image"] += 1
            continue
        for right in matches:
            lp, rp = left_label(image_path), right_label(right)
            if not lp.exists() or not rp.exists():
                counts["missing_label"] += 1
                continue
            result = classify(label(lp), label(rp))
            counts[result] += 1
            if len(examples[result]) < 4:
                examples[result].append(dict(left=str(lp), right=str(rp), image_sha256=image_hash,
                                             left_rows=label(lp), right_rows=label(rp)))
    emit("IMAGE_MATCH_COMPARE", comparison=name, left_root=str(left_root), counts=dict(counts), examples=dict(examples))


def varint(data, offset):
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
        shift += 7


def protobuf_fields(data):
    """Read protobuf wire fields without executing model code (ONNX package absent)."""
    pos = 0
    while pos < len(data):
        tag, pos = varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value, pos = varint(data, pos)
        elif wire == 2:
            size, pos = varint(data, pos)
            value = data[pos:pos + size]
            pos += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value, pos = data[pos:pos + size], pos + size
        else:
            raise ValueError(f"Unsupported protobuf wire type: {wire}")
        yield field, wire, value


def audit_models():
    import onnxruntime as ort
    emit("ONNX_RUNTIME", version=ort.__version__, providers=ort.get_available_providers(),
         action="CPU session load/introspection only; no session.run; no camera input")
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = 1
    opt.inter_op_num_threads = 1
    opt.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    for path in sorted((ROOT / "视觉/models").glob("*.onnx")):
        fields = list(protobuf_fields(path.read_bytes()))
        ir_version = next(v for f, w, v in fields if f == 1 and w == 0)
        opsets = []
        for f, w, value in fields:
            if f == 8 and w == 2:
                sub = {sf: sv for sf, _, sv in protobuf_fields(value)}
                opsets.append({"domain": sub.get(1, b"").decode(), "version": sub[2]})
        session = ort.InferenceSession(str(path), sess_options=opt, providers=["CPUExecutionProvider"])
        metadata = session.get_modelmeta().custom_metadata_map
        names = ast.literal_eval(metadata["names"]) if "names" in metadata else None
        emit("ONNX_MODEL", path=str(path), bytes=path.stat().st_size, sha256=sha(path),
             ir_version=ir_version, actual_opsets=opsets,
             inputs=[dict(name=x.name, shape=x.shape, dtype=x.type) for x in session.get_inputs()],
             outputs=[dict(name=x.name, shape=x.shape, dtype=x.type) for x in session.get_outputs()],
             embedded_metadata=metadata, embedded_names=names,
             class_count_from_embedded_names=len(names) if names is not None else None,
             CPU_session_load="PASS")
    emit("MUD_FILES_IN_MODELS", files=[str(p) for p in (ROOT / "视觉/models").glob("*.mud")])


def audit_voc():
    if not CURRENT.is_dir() or not VOC.is_dir():
        emit("VOC_AUDIT", status="missing source directory")
        return
    outcomes = Counter()
    object_names = Counter()
    mismatches = []
    for split in ("train", "val"):
        for txt in sorted((CURRENT / "labels" / split).glob("*.txt")):
            xml = VOC / "annotations" / (txt.stem + ".xml")
            if not xml.is_file():
                outcomes["missing_xml"] += 1
                continue
            root = ET.parse(xml).getroot()
            width, height = float(root.findtext("size/width")), float(root.findtext("size/height"))
            expected = []
            for obj in root.findall("object"):
                name = obj.findtext("name").strip()
                object_names[name] += 1
                xmin, ymin, xmax, ymax = [float(obj.findtext("bndbox/" + key)) for key in ("xmin", "ymin", "xmax", "ymax")]
                coords = tuple(round(v, 6) for v in ((xmin+xmax)/2/width, (ymin+ymax)/2/height, (xmax-xmin)/width, (ymax-ymin)/height))
                expected.append((CLASSES.index(name), coords))
            same = Counter(expected) == Counter(label(txt))
            outcomes["xml_name_and_box_match" if same else "label_mismatch"] += 1
            if not same and len(mismatches) < 5:
                mismatches.append(str(txt))
    emit("CURRENT_YOLO_VS_VOC", outcomes=dict(outcomes), object_names=dict(object_names), mismatches=mismatches,
         method="exact multiset of (class index from XML object name, normalized box rounded to six decimals)")


def main():
    emit("ENVIRONMENT", python=sys.version, executable=sys.executable, root=str(ROOT),
         dependencies={k: bool(importlib.util.find_spec(k)) for k in ("onnx", "onnxruntime", "numpy")})
    print("BOUNDARY: read-only datasets/models/configs; no model inference, device connection, training, remap execution, or production writes.")
    emit("REMAP_FACT", mapping=REMAP, fixed_points=[i for i in REMAP if REMAP[i] == i],
         id_set_before=sorted(REMAP), id_set_after=sorted(REMAP.values()),
         warning="0..6 range alone cannot distinguish the two class permutations; remap is not idempotent.")
    for p in (ROOT / "视觉/training/remap_labels.py", PRE / "class.txt", WS / "classes.txt",
              ROOT / "视觉/models/labels_yolo5s_geom7c.txt", ROOT / "视觉/training/data.yaml", CURRENT / "data.yaml"):
        text_file(p)
    label_stats(PRE / "labels")
    label_stats(WS, "img_*.txt")
    label_stats(PRE / "_unused/labels")
    label_stats(WS / "_unused", "img_*.txt")
    pre_images = sorted((PRE / "images").glob("*.jpg"))
    workspace_images = sorted(WS.glob("img_*.jpg"))
    current_images = sorted((CURRENT / "images").glob("*/*.jpg"))
    for name, paths in (("preliminary", pre_images), ("workspace_label", workspace_images), ("current_yolo", current_images)):
        emit("IMAGE_STATS", dataset=name, count=len(paths), count_by_parent=dict(Counter(str(p.parent) for p in paths)))
    current_index = image_index(current_images)
    ws_index = image_index(workspace_images)
    pre_label = lambda p: PRE / "labels" / (p.stem + ".txt")
    split_label = lambda p: p.parent.parent.parent / "labels" / p.parent.name / (p.stem + ".txt")
    compare_images(PRE, pre_images, ws_index, pre_label, lambda p: p.with_suffix(".txt"), "preliminary -> workspace_label")
    compare_images(PRE, pre_images, current_index, pre_label, split_label, "preliminary -> current_yolo")
    compare_images(WS, workspace_images, current_index, lambda p: p.with_suffix(".txt"), split_label, "workspace_label -> current_yolo")
    for p in (PRE / "labels/session_1787758510_img_00019.txt", WS / "img_00004.txt"):
        text_file(p)
    for p in (PRE / "images/session_1787758510_img_00019.jpg", WS / "img_00004.jpg"):
        emit("B07_SAMPLE_IMAGE", path=str(p), sha256=sha(p))
    for split in ("train", "val"):
        label_stats(CURRENT / "labels" / split)
    audit_voc()
    for p in (ROUND3 / "manifest.json", ROUND3 / "data.yaml",
              EXTERNAL / "ultralytics-8.3.163/runs/block_detector/block_yolo11n_e100_round3/args.yaml"):
        text_file(p)
    for split in ("train", "val", "test"):
        label_stats(ROUND3 / "labels" / split)
    round3_index = image_index((ROUND3 / "images/train").glob("ws_*.jpg"))
    compare_images(WS, workspace_images, round3_index, lambda p: p.with_suffix(".txt"), split_label, "workspace_label -> round3/ws_train")
    # Cohorts are selected by the saved pre-auto-label list, never by mtime.
    auto_stems = {Path(line.strip()).stem for line in (PRE / "unannotated.txt").read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.lstrip().startswith("#")}
    cohort_counts = Counter()
    for txt in sorted((PRE / "labels").glob("*.txt")):
        cohort = "listed_for_auto_label" if txt.stem in auto_stems else "preexisting_label"
        cohort_counts[cohort] += 1
        session, image_stem = txt.stem.rsplit("_img_", 1)
        archived = ROOT / "archive/datasets/raw-capture-2026-08-27" / session / ("img_" + image_stem + ".txt")
        if not archived.is_file():
            result = "archive_label_missing"
        elif Counter(label(txt)) == Counter(label(archived)):
            result = "archive_label_equal"
        elif not label(archived):
            result = "archive_label_empty"
        else:
            result = "archive_label_different"
        cohort_counts[cohort + "/" + result] += 1
    emit("PRELIMINARY_LABEL_COHORTS", saved_auto_input_count=len(auto_stems), counts=dict(cohort_counts),
         note="Saved list and archive establish provenance, not independent semantic ground truth for shapes.")
    text_file(ROOT / "archive/datasets/raw-capture-2026-08-27/session_1787758510/img_00019.txt")
    audit_models()
    print("AUDIT_COMPLETE: introspection only; 320x320 MaixCAM runtime configuration was not changed.")


if __name__ == "__main__":
    main()
