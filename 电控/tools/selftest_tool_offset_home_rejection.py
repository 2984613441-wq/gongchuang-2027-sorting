#!/usr/bin/env python3
"""T1/T2/T3 主机侧单文件自检；只用 assert，不访问串口/屏幕/硬件。"""

from __future__ import annotations

import importlib.util
import io
import logging
import os
import sys
from pathlib import Path


ELECTRICAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ELECTRICAL_ROOT / "src"))

from electrical_control.rpi.pixel_to_device import (  # noqa: E402
    PixelToDeviceConverter,
    make_grasp_point_for_target,
)
from electrical_control.rpi.vision_ingest import (  # noqa: E402
    BatchTargets,
    VisionTarget,
    build_item_task_queue,
)


def _load_run_chain():
    path = ELECTRICAL_ROOT / "deploy" / "run_chain.py"
    spec = importlib.util.spec_from_file_location("selftest_run_chain", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _config(path: Path, *, tool_offset: bool = True, heights: str = "3=0") -> Path:
    tool = "\n[ToolOffset]\nx_mm=-75\ny_mm=-25\n" if tool_offset else ""
    path.write_text(
        "[CameraCalibration]\n"
        "a11=0.5\na12=0\ntx=-50\na21=0\na22=0.5\nty=-100\n"
        "camera_height=200\n"
        f"[ObjectHeights]\n{heights}\n"
        "[WorkspaceLimits]\nx_min=-95\nx_max=90\ny_min=-97.5\ny_max=92.5\n"
        + tool,
        encoding="utf-8",
    )
    return path


def _queue(converter: PixelToDeviceConverter, target: VisionTarget):
    return build_item_task_queue(
        BatchTargets(1, (target,)),
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (0, 0),
        grasp_point_for_target=make_grasp_point_for_target(converter),
    )


def main() -> None:
    # 只在既有 tools/ 目录放短命配置；某些受限环境不允许访问新建临时目录。
    prefix = Path(__file__).resolve().parent / f".selftest-{os.getpid()}"
    paths = [Path(str(prefix) + suffix) for suffix in ("-old.ini", "-new.ini")]
    try:
        target = VisionTarget(1, 3, pixel_x=180, pixel_y=180, box_id=3)

        old = PixelToDeviceConverter(_config(paths[0], tool_offset=False))
        assert old.tool_offset_mm == (0.0, 0.0)
        assert old.pixel_to_device(180, 180, 3) == (400, -100)
        assert _queue(old, target)[0].pick_x_position == 400

        new = PixelToDeviceConverter(_config(paths[1]))
        # 偏移只在运动链适配器应用：pixel_to_device 基础结果不变。
        assert new.pixel_to_device(180, 180, 3) == (400, -100)
        item = _queue(new, target)[0]
        assert (item.pick_x_position, item.pick_y_position) == (-350, -350)

        logs = io.StringIO()
        handler = logging.StreamHandler(logs)
        logger = logging.getLogger("electrical_control.rpi.vision_ingest")
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
        try:
            assert _queue(new, VisionTarget(2, 3, pixel_x=180, pixel_y=100, box_id=3)) == ()
            assert "box_id=3" in logs.getvalue() and "pixel=(180,100)" in logs.getvalue()
            assert "像素域外" in logs.getvalue()

            logs.seek(0); logs.truncate(0)
            assert _queue(new, VisionTarget(3, 4, pixel_x=180, pixel_y=180, box_id=4)) == ()
            assert "件高表缺项" in logs.getvalue()

            logs.seek(0); logs.truncate(0)
            # 基础坐标 x=-21.5mm 合法；叠加 x=-75mm 后 PICK=-96.5mm 越界。
            assert _queue(new, VisionTarget(4, 3, pixel_x=57, pixel_y=180, box_id=3)) == ()
            assert "越界" in logs.getvalue()
        finally:
            logger.removeHandler(handler)

        chain = _load_run_chain()
        standby = chain.parse_args([])
        chain.require_home_confirmation(
            standby,
            input_fn=lambda _: (_ for _ in ()).throw(AssertionError("不应询问")),
            output=io.StringIO(),
        )
        args = chain.parse_args(["--start-round"])
        try:
            chain.require_home_confirmation(
                args, input_fn=lambda _: "NO", output=io.StringIO()
            )
            raise AssertionError("非 HOME 输入不应放行")
        except SystemExit as exc:
            assert "HOME 未确认" in str(exc)
        banner = io.StringIO()
        chain.require_home_confirmation(args, input_fn=lambda _: "HOME", output=banner)
        assert "无法自动判断" in banner.getvalue()
        assert "X=-95.0mm, Y=-97.5mm" in banner.getvalue()
        try:
            chain.require_home_confirmation(
                args,
                input_fn=lambda _: (_ for _ in ()).throw(EOFError()),
                output=io.StringIO(),
            )
            raise AssertionError("EOF 不应放行")
        except SystemExit as exc:
            assert "不可交互" in str(exc)
        fake = chain.parse_args(["--fake-link", "--start-round"])
        chain.require_home_confirmation(fake, input_fn=lambda _: (_ for _ in ()).throw(AssertionError()))

    finally:
        for path in paths:
            path.unlink(missing_ok=True)

    print("PASS: ToolOffset/三类拒识原因/HOME 门禁主机自检全部通过")


if __name__ == "__main__":
    main()
