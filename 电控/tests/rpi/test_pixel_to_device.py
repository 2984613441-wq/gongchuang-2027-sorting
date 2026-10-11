"""Host-only calibration regressions; synthetic geometry, no hardware I/O."""

from __future__ import annotations

import logging
from pathlib import Path
import runpy

import pytest

from electrical_control.protocol import (
    Command,
    PayloadError,
    decode_item_task_payload,
    decode_outer_frame,
    encode_item_task_payload,
)
from electrical_control.rpi import Scheduler, VerifiedNewRound
from electrical_control.rpi import pixel_to_device as calibration
from electrical_control.rpi.outbound import OutboundConfig, OutboundGateway
from electrical_control.rpi.serial_link import FakeSerialLink
from electrical_control.rpi.socket_vision_source import SocketVisionSource
from electrical_control.rpi.vision_ingest import (
    BatchTargets,
    VisionTarget,
    build_item_task_queue,
    parse_batch_targets,
)


# A(160,160) = (30,-20) mm; A(180,180) = (40,-10) mm.
# For box 3: H=200, h=40, scale=1.25 -> (38,-12) mm.
_VALID_CALIBRATION = {
    "a11": "0.5", "a12": "0", "tx": "-50",
    "a21": "0", "a22": "0.5", "ty": "-100",
    "camera_height": "200",
}
_BATCH = bytes.fromhex("010001035a00b400b4ff")  # box=3, (180,180) pixels
_TARGET = VisionTarget(1, 2, pixel_x=180, pixel_y=180, box_id=3)


def _write_config(
    tmp_path, *, overrides=None, heights="2=0\n3=40 # measured",
    limits=None, tool_offset=None,
):
    values = {**_VALID_CALIBRATION, **(overrides or {})}
    content = "[CameraCalibration]\n" + "\n".join(
        f"{key}={value}" for key, value in values.items()
    )
    content += "\n[ObjectHeights]\n" + heights + "\n"
    if limits is not None:
        content += "[WorkspaceLimits]\n" + limits + "\n"
    if tool_offset is not None:
        content += "[ToolOffset]\n" + tool_offset + "\n"
    path = tmp_path / "calibration.ini"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "overrides",
    [
        {key: "0" for key in ("a11", "a12", "tx", "a21", "a22", "ty")},
        {"a11": "1", "a12": "2", "a21": "2", "a22": "4"},
        {"a11": "1", "a12": "1", "a21": "1", "a22": "1.000000000001"},
        {"a11": "1e-12", "a22": "1e-12"},
        {"a11": "nan"},
        {"tx": "inf"},
        {"a11": "1e9"},
        {"ty": "1e9"},
        {"a11": "not-a-number"},
    ],
    ids=["all-zero", "singular", "nearly-singular", "tiny", "nan", "inf", "huge-scale", "huge-offset", "malformed"],
)
def test_invalid_affine_is_uncalibrated_and_logs_reason(tmp_path, caplog, overrides):
    with caplog.at_level(logging.ERROR):
        converter = calibration.PixelToDeviceConverter(_write_config(tmp_path, overrides=overrides))
    assert not converter.is_calibrated
    assert converter.pixel_to_device(180, 180, 3) is None
    assert any(record.levelno == logging.ERROR and record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("height", ["-1", "200", "201", "nan", "inf", "bad"])
def test_invalid_height_never_silently_disables_compensation(tmp_path, height):
    converter = calibration.PixelToDeviceConverter(_write_config(tmp_path, heights=f"3={height}"))
    assert converter.pixel_to_device(180, 180, 3) is None


@pytest.mark.parametrize("height", ["0", "-1", "nan", "inf"])
def test_invalid_camera_height_fails_closed(tmp_path, height):
    converter = calibration.PixelToDeviceConverter(
        _write_config(tmp_path, overrides={"camera_height": height}, heights="3=40")
    )
    assert not converter.is_calibrated
    assert converter.pixel_to_device(180, 180, 3) is None


@pytest.mark.parametrize("dimension", ["frame_width", "frame_height"])
def test_infinite_frame_size_is_uncalibrated(tmp_path, dimension):
    converter = calibration.PixelToDeviceConverter(
        _write_config(tmp_path, overrides={dimension: "inf"})
    )
    assert not converter.is_calibrated
    assert converter.pixel_to_device(180, 180, 3) is None


@pytest.mark.parametrize("limits", [
    "x_min=-inf\nx_max=inf\ny_min=-80\ny_max=80",
    "x_min=80\nx_max=-80\ny_min=-80\ny_max=80",
    "x_min=-80\nx_max=80\ny_min=-80\ny_max=146",
])
def test_invalid_workspace_cannot_admit_unserializable_coordinates(tmp_path, limits):
    converter = calibration.PixelToDeviceConverter(_write_config(tmp_path, limits=limits))
    assert not converter.is_calibrated
    assert converter.pixel_to_device(180, 180, 3) is None


def test_missing_configuration_returns_none_and_drops_target(tmp_path):
    converter = calibration.PixelToDeviceConverter(tmp_path / "missing.ini")
    assert not converter.is_calibrated
    grasp = calibration.make_grasp_point_for_target(converter)
    assert grasp(_TARGET) is None
    assert build_item_task_queue(
        BatchTargets(1, (_TARGET,)),
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
        grasp_point_for_target=grasp,
    ) == ()


def test_default_configuration_path_is_relative_to_electrical_root(tmp_path, monkeypatch):
    # A relocated source tree exercises the default path without editing the real INI.
    fake_module = tmp_path / "src/electrical_control/rpi/pixel_to_device.py"
    monkeypatch.setattr(calibration, "__file__", str(fake_module))
    _write_config(tmp_path).rename(tmp_path / "calibration_config.ini")
    converter = calibration.PixelToDeviceConverter()
    assert converter.is_calibrated
    assert converter.pixel_to_device(180, 180, 3) == (380, -120)


def test_adapter_uses_box_id_height_even_when_class_id_differs(tmp_path):
    converter = calibration.PixelToDeviceConverter(_write_config(tmp_path))
    assert converter.is_calibrated
    assert converter.pixel_to_device(180, 180, 2) == (400, -100)  # explicit h=0
    grasp = calibration.make_grasp_point_for_target(converter)
    assert grasp(_TARGET) == (380, -120)  # box_id=3, NOT class_id=2


def test_parallax_is_about_offset_nadir_and_preserves_optical_axis(tmp_path):
    converter = calibration.PixelToDeviceConverter(_write_config(tmp_path, heights="3=40"))
    assert converter.pixel_to_device(160, 160, 3) == (300, -200)
    result = converter.pixel_to_device(180, 180, 3)
    assert result == (380, -120)
    assert result != (500, -125)  # old device-origin formula


def test_affine_rotation_and_negative_determinant_are_valid(tmp_path):
    # A(160,160)=(30,-20); A(180,180)=(40,-10).
    converter = calibration.PixelToDeviceConverter(_write_config(
        tmp_path,
        overrides={"a11": "0", "a12": "0.5", "a21": "0.5", "a22": "0"},
        heights="3=40",
    ))
    assert converter.is_calibrated
    assert converter.pixel_to_device(180, 180, 3) == (380, -120)


def test_unknown_height_or_missing_box_id_is_rejected(tmp_path):
    converter = calibration.PixelToDeviceConverter(_write_config(tmp_path))
    assert converter.pixel_to_device(180, 180, 99) is None
    grasp = calibration.make_grasp_point_for_target(converter)
    assert grasp(VisionTarget(1, 3, pixel_x=180, pixel_y=120)) is None


def test_tool_offset_is_backward_compatible_and_applied_after_pixel_conversion(tmp_path):
    legacy = calibration.PixelToDeviceConverter(_write_config(tmp_path, heights="3=0"))
    assert legacy.tool_offset_mm == (0.0, 0.0)
    assert calibration.make_grasp_point_for_target(legacy)(_TARGET) == (400, -100)

    configured = calibration.PixelToDeviceConverter(_write_config(
        tmp_path, heights="3=0", tool_offset="x_mm=-75\ny_mm=-25",
    ))
    assert configured.pixel_to_device(180, 180, 3) == (400, -100)
    assert calibration.make_grasp_point_for_target(configured)(_TARGET) == (-350, -350)


def test_motion_chain_checks_workspace_after_tool_offset(tmp_path):
    converter = calibration.PixelToDeviceConverter(_write_config(
        tmp_path,
        heights="3=0",
        limits="x_min=-95\nx_max=30\ny_min=-80\ny_max=80",
        tool_offset="x_mm=-75\ny_mm=-25",
    ))
    # base x=66mm is outside x_max=30, but final PICK x=-9mm is reachable.
    assert converter.pixel_to_device(232, 180, 3) is None
    target = VisionTarget(1, 3, pixel_x=232, pixel_y=180, box_id=3)
    assert calibration.make_grasp_point_for_target(converter)(target) == (-90, -350)


def test_rejection_warning_distinguishes_pixel_domain_height_and_workspace(
    tmp_path, caplog,
):
    cases = (
        (
            calibration.PixelToDeviceConverter(_write_config(tmp_path, heights="3=0")),
            VisionTarget(1, 3, pixel_x=180, pixel_y=141, box_id=3),
            "像素域外",
        ),
        (
            calibration.PixelToDeviceConverter(_write_config(tmp_path, heights="3=0")),
            VisionTarget(2, 4, pixel_x=180, pixel_y=180, box_id=4),
            "件高表缺项",
        ),
        (
            calibration.PixelToDeviceConverter(_write_config(
                tmp_path, heights="3=0",
                limits="x_min=-20\nx_max=20\ny_min=-80\ny_max=80",
            )),
            _TARGET,
            "越界",
        ),
    )
    for converter, target, expected in cases:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            assert build_item_task_queue(
                BatchTargets(1, (target,)),
                image_id_for_class=lambda class_id: class_id,
                drop_point_for_box=lambda box_id: (0, 0),
                grasp_point_for_target=calibration.make_grasp_point_for_target(converter),
            ) == ()
        message = "\n".join(record.getMessage() for record in caplog.records)
        assert "box_id=" in message and "pixel=(" in message
        assert expected in message


@pytest.mark.parametrize("u,v", [(float("nan"), 120), (180, float("inf")), ("bad", 120), (None, 120)])
def test_invalid_pixels_return_none_without_raising(tmp_path, u, v):
    converter = calibration.PixelToDeviceConverter(_write_config(tmp_path, heights="3=40"))
    grasp = calibration.make_grasp_point_for_target(converter)
    assert grasp(VisionTarget(1, 2, pixel_x=u, pixel_y=v, box_id=3)) is None


def test_compensated_workspace_boundary_is_checked_before_queueing(tmp_path):
    # x_top=40 is in bounds but compensated x=38 is outside x_max=37.
    converter = calibration.PixelToDeviceConverter(_write_config(
        tmp_path, limits="x_min=-80\nx_max=37\ny_min=-80\ny_max=80",
    ))
    grasp = calibration.make_grasp_point_for_target(converter)
    assert grasp(_TARGET) is None
    valid = VisionTarget(2, 2, pixel_x=160, pixel_y=160, box_id=3)
    queue = build_item_task_queue(
        BatchTargets(1, (_TARGET, valid)),
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
        grasp_point_for_target=grasp,
    )
    assert len(queue) == 1
    assert queue[0].target_seq == 2
    assert (queue[0].pick_x_position, queue[0].pick_y_position) == (300, -200)


def test_omitted_source_callback_keeps_fail_closed_encoding():
    source = SocketVisionSource(
        round_id="round-1", task_id=1,
        image_id_for_class=lambda class_id: class_id,
        drop_point_for_box=lambda box_id: (100, 200),
    )
    source.set_permitted(True)
    source.ingest(_BATCH)
    task = source.next_if_permitted()
    assert task is not None
    assert task.payload.pick_x_position is None
    assert task.payload.pick_y_position is None
    with pytest.raises(PayloadError, match="grasp point missing"):
        encode_item_task_payload(task.payload)


@pytest.fixture(scope="module")
def chain_module():
    return runpy.run_path(str(Path(__file__).resolve().parents[2] / "deploy/run_chain.py"))


def test_live_factory_emits_calibrated_item_task_on_fake_link(tmp_path, chain_module):
    path = _write_config(tmp_path)
    args = chain_module["parse_args"](["--calibration-config", str(path)])
    source = chain_module["build_socket_source"](
        round_id="round-1", round_task_id=1,
        drop_point_for_box=lambda box_id: (100, 200),
        calibration_config=args.calibration_config,
    )
    # The existing uplink bytes retain pixel coordinates.
    target = parse_batch_targets(_BATCH).targets[0]
    assert (target.pixel_x, target.pixel_y, target.box_id) == (180, 180, 3)
    scheduler = Scheduler()
    scheduler.start_verified_new_round(VerifiedNewRound("round-1", True, True, True))
    scheduler.load_source(source)
    source.ingest(_BATCH)
    task = scheduler.next_task()
    assert task is not None
    link = FakeSerialLink()
    outbound = OutboundGateway(link, config=OutboundConfig(round_task_id=1))
    raw = outbound.send_item_task(task)
    assert link.sent == (raw,)  # FakeSerialLink.sent 是 tuple（serial_link.py:32）
    frame = decode_outer_frame(raw)
    assert frame.command == Command.ITEM_TASK
    assert len(frame.payload) == 12
    payload = decode_item_task_payload(frame.payload)
    assert (payload.pick_x_position, payload.pick_y_position) == (380, -120)
    assert (payload.x_position, payload.y_position) == (100, 200)
    assert (payload.class_id, payload.image_id, payload.grip_angle) == (3, 3, 0xFF)
    assert source.next_if_permitted() is None  # whole frame consumed once


@pytest.mark.parametrize("bad_config", ["missing", "zero", "malformed"])
def test_live_factory_rejects_uncalibrated_without_exception(tmp_path, chain_module, bad_config):
    path = tmp_path / "missing.ini"
    if bad_config == "zero":
        path = _write_config(tmp_path, overrides={key: "0" for key in _VALID_CALIBRATION if key != "camera_height"})
    elif bad_config == "malformed":
        path.write_text("not an ini file", encoding="utf-8")
    source = chain_module["build_socket_source"](
        round_id="round-1", round_task_id=1,
        drop_point_for_box=lambda box_id: (100, 200),
        calibration_config=path,
    )
    source.set_permitted(True)
    source.ingest(_BATCH)
    assert source.next_if_permitted() is None
