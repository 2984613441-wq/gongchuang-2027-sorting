"""Read-only host reproduction; never imports/runs a Maix camera main loop."""
from __future__ import annotations

import ast
import configparser
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import time
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / '电控/src'))

from electrical_control.protocol import encode_item_task_payload, decode_item_task_payload
from electrical_control.rpi import vision_ingest as ingest
from electrical_control.rpi.socket_vision_source import SocketVisionSource, recv_batch
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter, make_grasp_point_for_target


def out(name, value):
    print(name + ': ' + json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def selected_source(relative, names, namespace):
    path = ROOT / relative
    data = path.read_bytes()
    tree = ast.parse(data.decode('utf-8-sig'), filename=str(path))
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    out('extracted_source', {'path': relative, 'sha256': hashlib.sha256(data).hexdigest(),
                            'definitions': {n.name: [n.lineno, n.end_lineno] for n in nodes}})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def row(bin_id, bbox=(124, 170, 40, 40), color='cyan', frac=.83):
    return dict(bin=bin_id, bbox=bbox, color=color, shape='cube', color_fraction=frac)


def main():
    out('python', sys.version)
    out('scope', 'host only; source functions extracted by AST; no camera, serial or network connection')
    old = selected_source('视觉/src/maixcam_deploy/main.py', ['encode_batch_targets'], {'TASK_ID': 0})
    stage = selected_source('视觉/src/maixcam_deploy/stage1_color_v6_send.py',
                            ['encode_target', 'encode_batch_targets', 'StableTargets', 'BatchSender'],
                            dict(struct=struct, _ANGLE_NONE=255, _TARGET_BYTES=7, np=np,
                                 time=time, GATEWAY_HOST='unused-host-only', GATEWAY_PORT=8765,
                                 TASK_ID=1, ENABLE_NETWORK=False, MIN_SEND_INTERVAL_S=.10,
                                 MAX_TRACK_GAP=.65, SMOOTH_TIME=.22, CONFIRM_FRAMES=2, HOLD_SECONDS=.30))
    bridge = selected_source('视觉/src/maixcam_deploy/v6_bridge.py',
                             ['encode_target', 'encode_batch_targets'],
                             dict(struct=struct, ANGLE_NONE=255, TARGET_BYTES=7))
    rs = [row(1, (10, 20, 40, 40)), row(3, (100, 120, 30, 30)), row(None)]
    wire = stage['encode_batch_targets'](rs, 7)
    assert wire == bridge['encode_batch_targets'](rs, 7)
    assert wire.hex() == '0200070153001e0028ff035300730087ff'
    parsed = ingest.parse_batch_targets(wire)
    out('v6_golden_wire_hex', wire.hex())
    out('v6_parsed', vars(parsed) | {'targets': [vars(t) for t in parsed.targets]})
    assert [(t.class_id, t.box_id, t.pixel_x, t.pixel_y) for t in parsed.targets] == [(1, 1, 30, 40), (3, 3, 115, 135)]
    empty = stage['encode_batch_targets']([row(None), row(0), row(7)], 7)
    out('empty_wire', {'hex': empty.hex(), 'targets': len(ingest.parse_batch_targets(empty).targets)})
    assert empty == bytes.fromhex('000007')

    # Feed a fragmented + coalesced byte stream to the production framing function.
    class FragmentedStream:
        def __init__(self, data): self.data = data
        def recv(self, size):
            size = min(size, 2)
            part, self.data = self.data[:size], self.data[size:]
            return part
    stream = FragmentedStream(wire + empty)
    assert recv_batch(stream) == wire and recv_batch(stream) == empty and recv_batch(stream) is None
    out('fragmented_and_coalesced_stream', 'PASS (in-memory recv, no socket)')
    for desc, bad in [('truncated', wire[:-1]), ('confidence101', wire[:4] + bytes([101]) + wire[5:]),
                      ('angle0', wire[:9] + bytes([0]) + wire[10:])]:
        try:
            ingest.parse_batch_targets(bad)
        except Exception as exc:
            out('rejected_' + desc, {'type': type(exc).__name__, 'message': str(exc)})
        else:
            raise AssertionError(desc)

    old_objects = [SimpleNamespace(class_id=i, score=.83, x=10, y=20, w=40, h=40) for i in [0, 2, 3, 4, 5, 6]]
    old_wire = old['encode_batch_targets'](old_objects, task_id=7)
    old_parsed = ingest.parse_batch_targets(old_wire)
    out('old_main_in_school_mode', {'sent_ids': [o.class_id for o in old_objects], 'hex': old_wire.hex(),
                                   'parsed': [vars(t) for t in old_parsed.targets]})
    assert [t.box_id for t in old_parsed.targets] == [2, 3, 4, 5, 6]

    # Tracker consumes real dictionaries; images/HSV quality are NOT exercised.
    tr = stage['StableTargets']()
    first = tr.update([row(1)], 1.0)
    second = tr.update([row(1)], 1.2)
    held = tr.update([], 1.3)
    expired = tr.update([], 1.6)
    out('tracker_confirm_hold_expire', {'first': len(first), 'second_bins': [r['bin'] for r in second],
                                       'held_bins': [r['bin'] for r in held],
                                       'held_wire_count': stage['encode_batch_targets'](held, 1)[0],
                                       'expired': len(expired)})
    assert not first and len(second) == 1 and held[0]['bin'] is None and not expired
    tr2 = stage['StableTargets']()
    same = [row(1, (100, 100, 40, 40)), row(1, (110, 100, 40, 40))]
    same_result = tr2.update(same, 2.0)
    out('same_color_tracker', {'input_rows': 2, 'tracks': len(tr2.tracks), 'output_rows': len(same_result)})
    assert len(tr2.tracks) == 1

    spec = importlib.util.spec_from_file_location('vision_audit_run_chain', ROOT / '电控/deploy/run_chain.py')
    chain = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(chain)  # main guarded; importing does not connect any device
    names = chain.load_names(str(ROOT / '工具/generated_names.json'), demo=False)
    config = ROOT / '电控/deploy/sorting_config.ini'
    converter = PixelToDeviceConverter(ROOT / '电控/calibration_config.ini')
    points = chain.load_drop_points(str(config))
    fixed = chain.load_fixed_pick_point(str(config))
    out('local_config', {'names': names, 'drop_points_mm10': points, 'fixed_pick_mm10': fixed,
                         'box_map': chain.load_box_map(str(config)), 'converter_is_calibrated': converter.is_calibrated,
                         'frame_size': [converter.frame_width, converter.frame_height], 'heights': converter.object_heights})
    batch = ingest.parse_batch_targets(stage['encode_batch_targets']([row(i) for i in range(1, 7)], 1))
    items = ingest.build_item_task_queue(batch, image_id_for_class=chain._identity_image_id,
                                         drop_point_for_box=points.get, grasp_point_for_target=make_grasp_point_for_target(converter))
    assert len(items) == 6
    for item in items:
        encoded = encode_item_task_payload(item)
        assert decode_item_task_payload(encoded) == item
        out('school_item', {'payload': vars(item), 'name': names.get(item.class_id), 'wire_hex': encoded.hex()})
    source = chain.build_socket_source(round_id='host-audit', round_task_id=1,
                                       drop_point_for_box=points.get,
                                       calibration_config=str(ROOT / '电控/calibration_config.ini'),
                                       fixed_pick_point=fixed)
    source.set_permitted(True)
    source.ingest(stage['encode_batch_targets']([row(1), row(3)], 1))
    context = source.next_if_permitted()
    assert context is not None and source.next_if_permitted() is None
    out('one_item_per_batch', {'payload': vars(context.payload), 'two_stage': vars(chain._two_stage_info(context, names))})
    assert (context.payload.pick_x_position, context.payload.pick_y_position) != fixed
    for task_id in [0, 2]:
        source.ingest(stage['encode_batch_targets']([row(1)], task_id))
        assert source.next_if_permitted() is None
        out('foreign_task_id', {'task_id': task_id, 'emitted': 0})
    source.set_permitted(False)
    source.ingest(stage['encode_batch_targets']([row(3)], 1))
    sender = stage['BatchSender'](enable=False)
    empty_sent = sender.send([], now=10.0)
    source.set_permitted(True)
    cached = source.next_if_permitted()
    assert empty_sent == 0 and cached is not None and cached.payload.class_id == 3
    out('empty_frame_does_not_clear_latest', {'empty_sent': empty_sent,
                                            'skipped_frames': sender.skipped_frames,
                                            'previous_box_emitted_after_permit': cached.payload.class_id})
    # Flag restored even on error; no production file mutation.
    prev = ingest.BATCH_ID_BYTE_IS_BOX_ID
    try:
        ingest.BATCH_ID_BYTE_IS_BOX_ID = False
        shape_batch = ingest.parse_batch_targets(old_wire)
        out('shape_mode', {'ids': [t.class_id for t in shape_batch.targets],
                           'boxes': [t.box_id for t in shape_batch.targets],
                           'expanded': len(source._expand(shape_batch))})
        assert source._expand(shape_batch) == []
    finally:
        ingest.BATCH_ID_BYTE_IS_BOX_ID = prev
    out('audit_result', 'PASS: observations reproduced; does not certify field recognition or physical sorting')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    main()
