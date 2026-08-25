from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

TRAINING = Path(__file__).resolve().parents[1] / "training"
sys.path.insert(0, str(TRAINING))

from prepare_voc_dataset import DatasetError, prepare


class PrepareVocDatasetTests(unittest.TestCase):
    def _make_voc_source(self, root: Path) -> None:
        classes = ("a", "b", "c")
        for class_id, class_name in enumerate(classes):
            for index in range(3):
                stem = f"{class_name}_{index}"
                image = Image.new("RGB", (64, 64), (10 * class_id, 40, 40))
                image.save(root / "images" / f"{stem}.jpg")
                xmin, ymin, xmax, ymax = 8 + index, 8 + index, 40 + index, 48 + index
                xml = (
                    "<annotation><size><width>64</width><height>64</height><depth>3</depth></size>"
                    f"<object><name>{class_name}</name>"
                    "<bndbox>"
                    f"<xmin>{xmin}</xmin><ymin>{ymin}</ymin>"
                    f"<xmax>{xmax}</xmax><ymax>{ymax}</ymax>"
                    "</bndbox></object></annotation>"
                )
                (root / "xml" / f"{stem}.xml").write_text(xml, encoding="utf-8")

    def test_prepare_creates_split_dataset_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            output = base / "output"
            (source / "images").mkdir(parents=True)
            (source / "xml").mkdir(parents=True)
            self._make_voc_source(source)

            manifest = prepare(
                source,
                output,
                classes=["a", "b", "c"],
                val_ratio=0.1,
                test_ratio=0.1,
                seed=7,
            )

            for split in ("train", "val", "test"):
                self.assertTrue((output / "images" / split).is_dir())
                self.assertTrue((output / "labels" / split).is_dir())
            self.assertTrue((output / "data.yaml").is_file())
            self.assertTrue((output / "manifest.json").is_file())
            self.assertEqual(["a", "b", "c"], manifest["classes"])
            for split in ("train", "val", "test"):
                self.assertGreaterEqual(manifest["split_stats"][split]["images"], 1)

    def test_prepare_rejects_unknown_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            output = base / "output"
            (source / "images").mkdir(parents=True)
            (source / "xml").mkdir(parents=True)
            self._make_voc_source(source)
            bad_xml = next((source / "xml").glob("*.xml"))
            bad_xml.write_text(
                "<annotation><size><width>64</width><height>64</height></size>"
                "<object><name>unknown</name><bndbox>"
                "<xmin>1</xmin><ymin>1</ymin><xmax>20</xmax><ymax>20</ymax>"
                "</bndbox></object></annotation>",
                encoding="utf-8",
            )
            with self.assertRaises(DatasetError):
                prepare(source, output, classes=["a", "b", "c"], val_ratio=0.1, test_ratio=0.1, seed=7)


if __name__ == "__main__":
    unittest.main()
