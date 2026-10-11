"""屏幕两段显示（2026-09-18 用户要求：识别到物体 → 分拣成功）的 host 测试。

覆盖三条渲染路径：
  · ``TwoStageDisplay.show_recognized()`` —— 段1 物体信息
  · ``TwoStageDisplay.show_success()``    —— 段2 分拣成功
  · ``TableDisplay.show_table()``         —— 累计分拣统计表（序号|预置图片|个数）
外加 ``display.split_color_shape()``（颜色/形状只能从本地名称拆，线格式里没有）。

纯 host：frame_output 用 ``list.append`` 捕获，不碰 /dev/fb0、不碰串口、不碰 run_chain。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from electrical_control.rpi.display import split_color_shape
from electrical_control.rpi.display_hdmi import (
    DEFAULT_TABLE_IMAGES,
    ImageLoadError,
    TableDisplay,
    TwoStageDisplay,
    TwoStageInfo,
    jpeg_dir_loader,
    table_image_path,
)

try:
    from PIL import Image
except ImportError:  # 模块本身无 Pillow 也应能 import（懒加载）
    Image = None


def _runtime_writes_allowed() -> bool:
    """本机是否允许测试运行时写文件。

    DSH 沙箱（2026-09-18 实测）允许 ``mkdir``，但**拒绝一切运行期文件创建**
    （``plain.txt`` / ``.jpeg`` / 无扩展名，%TEMP% 与工作区一样都是 Errno 13），
    并且**拒绝删除** —— 所以探测目录一律建在系统 %TEMP%，绝不建在 tests/ 下：
    建在仓库里会让 pytest 去 scandir 它并直接 collection error。
    """

    directory = tempfile.mkdtemp(prefix="ec_probe_")  # 系统临时目录，不进仓库
    try:
        with open(os.path.join(directory, "probe"), "wb") as handle:
            handle.write(b"x")
        return True
    except OSError:
        return False
    finally:
        shutil.rmtree(directory, ignore_errors=True)


_CAN_WRITE = _runtime_writes_allowed()

SCREEN = (1024, 600)
BG = (14, 22, 40)
ACCENT = (88, 166, 255)
SUCCESS = (96, 220, 120)
FAILURE = (240, 90, 90)

# 统计表版面（须与 display_hdmi 的常量一致；这里是刻意的重复，
# 好让「版面被改窄/改矮」立刻挂测试，而不是悄悄挤掉最后一行）
_TABLE_TOP = 92
_TABLE_ROW_H = 82
_TABLE_THUMB = 64
_THUMB_X = (180 + 420 - _TABLE_THUMB) // 2


def _crop_bytes(frame, box) -> bytes:
    """区域原始 RGB 字节（3 字节/像素）。用 tobytes 而非 getdata：后者在 Pillow 12 已弃用。"""
    return frame.crop(box).tobytes()


def count_color(frame, box, color, tolerance: int = 12) -> int:
    data = _crop_bytes(frame, box)
    return sum(
        1
        for at in range(0, len(data), 3)
        if all(abs(data[at + i] - color[i]) <= tolerance for i in range(3))
    )


def count_drawn(frame, box) -> int:
    """区域内非背景像素数 = 真的画上了东西（防"合成成功但整幅是底色"）。"""
    data = _crop_bytes(frame, box)
    background = bytes(BG)
    return sum(1 for at in range(0, len(data), 3) if data[at : at + 3] != background)


@unittest.skipIf(Image is None, "Pillow not installed")
class TwoStageDisplayTests(unittest.TestCase):
    def make(self) -> tuple[TwoStageDisplay, list]:
        frames: list = []
        return TwoStageDisplay(frame_output=frames.append), frames

    @staticmethod
    def info(**overrides) -> TwoStageInfo:
        base = dict(
            target_seq=3, box_id=3, name="红色三棱柱", color="红色", shape="三棱柱"
        )
        base.update(overrides)
        return TwoStageInfo(**base)

    def test_both_stages_are_1024x600_rgb_and_output_exactly_once(self) -> None:
        display, frames = self.make()

        first = display.show_recognized(self.info())
        second = display.show_success(self.info())

        self.assertEqual(2, len(frames))
        self.assertIs(frames[0], first)  # 返回的就是交给 frame_output 的那一帧
        self.assertIs(frames[1], second)
        for frame in frames:
            self.assertEqual(SCREEN, frame.size)
            self.assertEqual("RGB", frame.mode)

    def test_recognized_frame_draws_title_seq_and_all_four_rows(self) -> None:
        display, frames = self.make()
        display.show_recognized(self.info())
        frame = frames[0]

        self.assertGreater(count_color(frame, (48, 30, 500, 96), ACCENT), 0)  # 标题
        self.assertGreater(count_drawn(frame, (48, 120, 900, 230)), 0)        # 第 N 件
        for row in range(4):  # 货格号 / 名称 / 颜色 / 形状 四行
            y = 250 + row * 88
            self.assertGreater(
                count_drawn(frame, (48, y, 1000, y + 80)),
                0,
                f"第 {row + 1} 行是空的（y={y}）",
            )

    def test_recognized_frame_changes_with_the_item(self) -> None:
        """换一个件，像素必须变 —— 否则信息没有真的进画面。"""
        display, frames = self.make()
        display.show_recognized(self.info())
        display.show_recognized(self.info(target_seq=5, box_id=5, name="黑色圆柱",
                                          color="黑色", shape="圆柱"))

        self.assertNotEqual(frames[0].tobytes(), frames[1].tobytes())

    def test_unknown_fields_render_as_dash_and_do_not_crash(self) -> None:
        display, frames = self.make()
        display.show_recognized(TwoStageInfo(target_seq=1))  # 只知序号

        self.assertEqual(SCREEN, frames[0].size)
        self.assertGreater(count_drawn(frames[0], (260, 250, 1000, 530)), 0)

    def test_success_frame_is_green_titled(self) -> None:
        display, frames = self.make()
        display.show_success(self.info())
        frame = frames[0]

        # 「分拣成功」四个大字：绿色像素必须成片出现（不是零散抗锯齿）
        self.assertGreater(count_color(frame, (150, 100, 900, 290), SUCCESS), 500)
        self.assertGreater(count_color(frame, (48, 316, 976, 324), SUCCESS), 0)  # 分隔线

    def test_success_frame_shows_more_when_box_color_shape_known(self) -> None:
        display, frames = self.make()
        display.show_success(TwoStageInfo(target_seq=3))
        display.show_success(self.info())

        self.assertNotEqual(frames[0].tobytes(), frames[1].tobytes())

    def test_success_detail_skips_unknown_parts(self) -> None:
        # 私有但纯：直接断言文案比逐像素比字稳。缺的字段整段不出现（不留 "—"）。
        display, _ = self.make()
        self.assertEqual("第 3 件 · 货格 3 · 红色 · 三棱柱",
                         display._success_detail(self.info()))
        self.assertEqual("第 1 件", display._success_detail(TwoStageInfo(target_seq=1)))

    def test_seq_no_is_the_on_screen_number_and_both_stages_agree(self) -> None:
        """🔴 回归：2026-09-22 上一版渲染函数直接读 `info.success_count`，而
        `TwoStageInfo` **没有那个字段** ⇒ 每件一条 AttributeError ⇒ 整帧合成失败
        ⇒ **屏幕整轮空白**（链只记 ERROR 不停链，所以肉眼才看得见）。

        本条一次钉四件事：
          ① 字段**真的存在**（上一版就是漏了它，读一下就 AttributeError）；
          ② 两条渲染路径都**真的产出帧**（抛异常时 frames 不会增长）；
          ③ 序号取自 `seq_no`（本轮第几件），**不取会重复回退的 target_seq**；
          ④ 未接线（seq_no=None）时退回 target_seq，未升级调用方不炸。
        """

        # ① 字段存在
        self.assertIsNone(TwoStageInfo(target_seq=1).seq_no)

        display, frames = self.make()
        # 故意让 target_seq ≠ seq_no：target_seq 会重复回退，正是要弃用的那个
        info = self.info(target_seq=6, seq_no=4)

        display.show_recognized(info)
        display.show_success(info)

        # ② 两帧都真的合成了（AttributeError 时这里只有 0 帧）
        self.assertEqual(2, len(frames))

        # ③ 段2 文案与两条路径共用的序号函数都取 seq_no
        self.assertEqual("第 4 件 · 货格 3 · 红色 · 三棱柱",
                         display._success_detail(info))
        self.assertEqual("第 4 件", display._seq_text(info))

        # ④ 未接线时退回旧行为（host 测试与未升级调用方靠它不炸）
        self.assertEqual("第 6 件", display._seq_text(TwoStageInfo(target_seq=6)))

    def test_invalid_size_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TwoStageDisplay(frame_output=lambda frame: None, width=0)


class SplitColorShapeTests(unittest.TestCase):
    def test_splits_color_and_shape_from_local_name(self) -> None:
        self.assertEqual(("青色", "正方体"), split_color_shape("青色正方体"))
        self.assertEqual(("红色", "三棱柱"), split_color_shape("红色三棱柱"))
        self.assertEqual(("橙色", "圆柱"), split_color_shape("橙色圆柱"))

    def test_name_without_a_color_word_keeps_whole_name_as_shape(self) -> None:
        self.assertEqual((None, "锂离子电池"), split_color_shape("锂离子电池"))
        self.assertEqual((None, None), split_color_shape(""))


@unittest.skipIf(Image is None, "Pillow not installed")
class TableDisplayTests(unittest.TestCase):
    """累计分拣统计表：六行 · 三列，且计数真的进画面。"""

    @staticmethod
    def solid(seq: int):
        """每序号一个不同纯色，便于判断「哪张图进了哪一格」。"""
        return Image.new("RGB", (96, 128), (20 * seq, 60, 200))

    def make(self, loader=None) -> tuple[TableDisplay, list]:
        frames: list = []
        loader = loader or self.solid
        return (
            TableDisplay(frame_output=frames.append, image_loader=loader),
            frames,
        )

    def test_frame_is_1024x600_rgb_and_output_exactly_once(self) -> None:
        display, frames = self.make()

        frame = display.show_table({1: 1})

        self.assertEqual(1, len(frames))
        self.assertIs(frames[0], frame)  # 返回的就是交给 frame_output 的那一帧
        self.assertEqual(SCREEN, frame.size)
        self.assertEqual("RGB", frame.mode)

    def test_all_six_rows_draw_seq_thumbnail_and_count(self) -> None:
        display, frames = self.make()
        display.show_table({seq: seq for seq in range(1, 7)})
        frame = frames[0]

        for index in range(6):
            y = _TABLE_TOP + index * _TABLE_ROW_H
            # 序号列 / 个数列：文字（裁掉行分隔线，避免线把空格子撑成"非空"）
            self.assertGreater(
                count_drawn(frame, (32, y + 6, 180, y + 76)), 0, f"序号列第 {index + 1} 行是空的"
            )
            self.assertGreater(
                count_drawn(frame, (420, y + 6, 992, y + 76)), 0, f"个数列第 {index + 1} 行是空的"
            )
            # 图片列：缩略图必须几乎铺满 64x64 的格子
            ty = y + (_TABLE_ROW_H - _TABLE_THUMB) // 2
            self.assertGreater(
                count_drawn(frame, (_THUMB_X, ty, _THUMB_X + _TABLE_THUMB, ty + _TABLE_THUMB)),
                _TABLE_THUMB * _TABLE_THUMB // 2,
                f"图片列第 {index + 1} 行没有真的贴上缩略图",
            )

    def test_row_uses_the_image_for_that_row_not_the_first_one(self) -> None:
        """🔴 回归：第 N 行必须取第 N 张图（DEFAULT_TABLE_IMAGES 的映射）。"""
        display, frames = self.make()
        display.show_table({})
        frame = frames[0]

        ty = _TABLE_TOP + 4 * _TABLE_ROW_H + (_TABLE_ROW_H - _TABLE_THUMB) // 2
        # 第 5 行 = 序号 5 = solid(5) = (100, 60, 200)
        self.assertGreater(
            count_color(
                frame, (_THUMB_X, ty, _THUMB_X + _TABLE_THUMB, ty + _TABLE_THUMB),
                (100, 60, 200),
            ),
            _TABLE_THUMB * _TABLE_THUMB // 2,
        )

    def test_counts_reach_the_screen(self) -> None:
        display, frames = self.make()
        display.show_table({seq: 0 for seq in range(1, 7)})
        display.show_table({1: 7, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0})

        self.assertNotEqual(frames[0].tobytes(), frames[1].tobytes())

    def test_missing_image_marks_that_cell_instead_of_blanking_the_screen(self) -> None:
        def loader(seq):
            if seq == 4:
                raise FileNotFoundError("image3.jpeg")
            return self.solid(seq)

        display, frames = self.make(loader)
        with self.assertLogs("electrical_control.rpi.display_hdmi", level="WARNING"):
            display.show_table({1: 1})
        frame = frames[0]

        self.assertEqual(SCREEN, frame.size)  # 缺图不掀桌
        ty = _TABLE_TOP + 3 * _TABLE_ROW_H + (_TABLE_ROW_H - _TABLE_THUMB) // 2
        self.assertGreater(  # 缺的那格：红框 + 「缺图」
            count_color(
                frame, (_THUMB_X, ty, _THUMB_X + _TABLE_THUMB, ty + _TABLE_THUMB), FAILURE
            ),
            30,
        )
        ty1 = _TABLE_TOP + (_TABLE_ROW_H - _TABLE_THUMB) // 2
        self.assertGreater(  # 其余五格照常
            count_drawn(frame, (_THUMB_X, ty1, _THUMB_X + _TABLE_THUMB, ty1 + _TABLE_THUMB)), 0
        )

    def test_loader_returning_a_non_image_is_handled_like_a_missing_one(self) -> None:
        display, frames = self.make(lambda seq: "not an image")

        display.show_table({1: 1})

        self.assertEqual(SCREEN, frames[0].size)

    def test_invalid_size_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TableDisplay(frame_output=lambda frame: None, image_loader=self.solid, height=0)


class TableImagePathTests(unittest.TestCase):
    """🔴 「行序号 → 文件名」这一跳是整张表最易错的地方，且**不需要文件系统**就能测。

    DEFAULT_TABLE_IMAGES 的顺序与 imageN 的顺序不一致，有人按 imageN 顺手重排就会
    把六张图全放错格 —— 这两条用例就是拦它的。
    """

    def test_row_2_maps_to_image6_not_image2(self) -> None:
        self.assertTrue(table_image_path("/imgs", 2).endswith("image6.jpeg"))
        self.assertTrue(table_image_path("/imgs", 3).endswith("image2.jpeg"))

    def test_every_row_maps_to_its_mapped_filename(self) -> None:
        for seq, name in DEFAULT_TABLE_IMAGES.items():
            self.assertEqual(
                os.path.join("/imgs", name), table_image_path("/imgs", seq)
            )

    def test_row_order_is_deliberately_not_the_filename_order(self) -> None:
        """有人「顺手」把它改成 image1..image6 的顺序就会挂在这里。"""
        self.assertNotEqual(
            [DEFAULT_TABLE_IMAGES[seq] for seq in sorted(DEFAULT_TABLE_IMAGES)],
            [f"image{n}.jpeg" for n in range(1, 7)],
        )

    def test_mapping_covers_rows_1_to_6_with_distinct_files(self) -> None:
        self.assertEqual([1, 2, 3, 4, 5, 6], sorted(DEFAULT_TABLE_IMAGES))
        names = list(DEFAULT_TABLE_IMAGES.values())
        self.assertEqual(len(names), len(set(names)), "两行指向了同一张图")

    def test_unknown_row_raises_image_load_error(self) -> None:
        with self.assertRaises(ImageLoadError):
            table_image_path("/imgs", 99)


@unittest.skipIf(Image is None, "Pillow not installed")
@unittest.skipUnless(_CAN_WRITE, "本机不允许运行期写文件（沙箱），无法落盘再读")
class JpegDirLoaderTests(unittest.TestCase):
    """``jpeg_dir_loader`` 真的把字节读回来的实测（需要能写文件的环境）。"""

    def tempdir(self) -> str:
        # 系统临时目录，不建在仓库里（理由见 _runtime_writes_allowed）
        path = tempfile.mkdtemp(prefix="ec_jpeg_")
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def test_reads_by_row_index_not_by_filename_order(self) -> None:
        tmp = self.tempdir()
        for seq, name in DEFAULT_TABLE_IMAGES.items():
            Image.new("RGB", (16, 16), (seq * 25, 0, 0)).save(
                os.path.join(tmp, name), "JPEG"
            )
        loader = jpeg_dir_loader(tmp)

        # 第 2 行 = image6.jpeg（红通道 50），**不是** image2.jpeg（红通道 25）。
        # JPEG 有损，给 ±5 容差。
        self.assertLess(abs(loader(2).getpixel((8, 8))[0] - 50), 5)

    def test_unknown_row_and_missing_file_both_raise(self) -> None:
        loader = jpeg_dir_loader(self.tempdir())  # 空目录
        with self.assertRaises(ImageLoadError):
            loader(99)   # 行号不在映射里
        with self.assertRaises(OSError):
            loader(1)    # 映射里有，但文件不在


if __name__ == "__main__":
    unittest.main()
