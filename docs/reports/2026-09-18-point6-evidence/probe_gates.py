"""Local audit probes only; never opens UART, starts a listener, or writes fb0."""
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/'电控/deploy'), str(ROOT/'电控/src')]
import run_chain as chain
from electrical_control.rpi import Scheduler
from electrical_control.rpi.display import build_display_view
from electrical_control.rpi.drop_strategy import load_strategy_from_config
from electrical_control.rpi import display_hdmi as hdmi
from electrical_control.rpi.outbound import OutboundConfig
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter

logger = logging.getLogger('point6-probe')
rows = []


def probe(label, fn, expected=None):
    try:
        value = fn()
    except (Exception, SystemExit) as exc:
        row = dict(case=label, outcome=type(exc).__name__, detail=str(exc),
                   pass_=expected is not None and isinstance(exc, expected))
    else:
        row = dict(case=label, outcome='returned', detail=repr(value), pass_=expected is None)
    rows.append(row)
    print(json.dumps(row, ensure_ascii=False))


def run_probes():
    # Persistent, audit-owned fixtures: no recursive cleanup or project mutation.
    temp = Path(__file__).parent/'gate-fixtures'
    def cfg(text):
        p = temp/'probe.ini'
        p.write_text(text, encoding='utf-8')
        return p
    a = '[DropPoints]\n' + ''.join(f'{i} = 5,5\n' for i in range(1,7))
    b = '[TurntableAngles]\nturntable_drop_point=5,5\n' + ''.join(f'{i} = {60*(i-1)}\n' for i in range(1,7))
    # All run() invocations below exit before configuration, monitor or serial construction.
    for name, port, rid, tid in [('missing-port', None, 'r1', 1),
                               ('missing-round-id', 'not-opened', None, 1),
                               ('missing-round-task-id', 'not-opened', 'r1', None)]:
        probe(name, lambda p=port,r=rid,t=tid: chain.run(SimpleNamespace(
            verbose=False, fake_link=False, port=p, round_id=r, round_task_id=t)), SystemExit)
    probe('A-missing-file', lambda: load_strategy_from_config(temp/'absent'), SystemExit)
    probe('A-missing-section', lambda: load_strategy_from_config(cfg('[Other]\na=1')), SystemExit)
    probe('A-missing-box-6', lambda: load_strategy_from_config(cfg(a.replace('6 = 5,5\n',''))), SystemExit)
    probe('A-malformed-box-6', lambda: load_strategy_from_config(cfg(a.replace('6 = 5,5','6 = nope'))), SystemExit)
    probe('A-nan-coordinate', lambda: load_strategy_from_config(cfg(a.replace('6 = 5,5','6 = nan,5'))), ValueError)
    probe('A-inf-coordinate', lambda: load_strategy_from_config(cfg(a.replace('6 = 5,5','6 = inf,5'))), OverflowError)
    probe('A-valid-six', lambda: load_strategy_from_config(cfg(a)).get_drop_point(6))
    probe('A-unknown-box-rejects-item', lambda: load_strategy_from_config(cfg(a)).get_drop_point(7))
    probe('A-finite-outside-mechanical-domain-is-not-startup-checked',
          lambda: load_strategy_from_config(cfg(a.replace('6 = 5,5','6 = 100,100'))).get_drop_point(6))
    probe('B-missing-drop', lambda: load_strategy_from_config(cfg('[TurntableAngles]\n1=0')), SystemExit)
    probe('B-invalid-drop', lambda: load_strategy_from_config(cfg(b.replace('5,5','bad'))), SystemExit)
    probe('B-missing-angle', lambda: load_strategy_from_config(cfg(b.replace('6 = 300\n',''))), SystemExit)
    probe('B-valid-six', lambda: load_strategy_from_config(cfg(b)).get_drop_point(1))
    probe('B-nan-angle-is-not-rejected', lambda: load_strategy_from_config(cfg(b.replace('1 = 0','1 = nan'))).get_angle(1))
    probe('BoxMap-absent', lambda: chain.load_box_map(cfg(a)))
    probe('BoxMap-invalid-entries-skipped', lambda: chain.load_box_map(cfg('[BoxMap]\nwrong=1\n1,2=7\n3,4=bad')))
    probe('PickPoint-invalid-returns-None', lambda: chain.load_fixed_pick_point(cfg('[PickPoint]\nx=nan\ny=0')))
    probe('names-argument-missing', lambda: chain.load_names(None,demo=False), SystemExit)
    probe('names-file-missing', lambda: chain.load_names(str(temp/'absent.json'),demo=False), FileNotFoundError)
    p=temp/'names.json'
    p.write_text('{bad',encoding='utf-8')
    probe('names-malformed-json', lambda: chain.load_names(str(p),demo=False), ValueError)
    p.write_text('{"bad":"name"}',encoding='utf-8')
    probe('names-noninteger-key', lambda: chain.load_names(str(p),demo=False), ValueError)
    p.write_text('{"2":"红方柱"}',encoding='utf-8')
    probe('names-incomplete-accepted-at-startup', lambda: chain.load_names(str(p),demo=False))
    probe('names-missing-1-fails-at-render', lambda: build_display_view(
        SimpleNamespace(class_id=1), {0:'红球',2:'红方柱',3:'红圆柱',4:'蓝圆柱',5:'蓝方柱',6:'蓝球'}),ValueError)
    probe('font-explicit-missing', lambda: chain.resolve_font(str(temp/'absent.ttf'),logger),SystemExit)
    with patch.object(chain.os.path,'exists',return_value=False):
        probe('font-default-missing-only-warns', lambda: chain.resolve_font(None,logger))
    probe('image-dir-argument-missing', lambda: chain.build_image_loader(None,demo=False), SystemExit)
    loader=chain.build_image_loader(str(temp/'missing-images'),demo=False)
    probe('missing-image-dir-loader-created', lambda: callable(loader))
    probe('missing-image-fails-on-load', lambda: loader(1), FileNotFoundError)
    probe('real-auto-refused', lambda: chain.build_frame_output('auto',str(temp),logger,demo=False),SystemExit)
    probe('real-none-only-warns', lambda: callable(chain.build_frame_output('none',str(temp),logger,demo=False)))
    probe('real-file-accepted', lambda: callable(chain.build_frame_output('file',str(temp),logger,demo=False)))
    with patch('builtins.open',side_effect=PermissionError('MOCK no framebuffer access')):
        probe('fb0-open-denied', lambda: chain.build_frame_output('fb0',str(temp),logger,demo=False),SystemExit)
    for name, values in [('missing-bpp',{}),('unsupported-bpp',{'bits_per_pixel':'8'}),
                         ('missing-size',{'bits_per_pixel':'16'}),
                         ('valid-16bpp',{'bits_per_pixel':'16','virtual_size':'1024,600','stride':'2048'})]:
        with patch.object(hdmi,'_read_sysfs',side_effect=lambda p,v=values: v.get(p.rsplit('/',1)[-1])):
            probe(name,lambda: hdmi.read_framebuffer_format(),None if name=='valid-16bpp' else hdmi.FramebufferFormatError)
    probe('frame-larger-than-device',lambda: hdmi.validate_frame_size(1024,600,hdmi.FramebufferFormat(16,800,600,None)),hdmi.FramebufferFormatError)
    probe('round-task-id-outside-u16',lambda: OutboundConfig(65536),ValueError)
    probe('scheduler-no-start-round-stays-locked',lambda: (Scheduler().state.name,Scheduler().next_task()))
    probe('current-local-PickPoint',lambda: chain.load_fixed_pick_point(ROOT/'电控/deploy/sorting_config.ini'))
    probe('current-local-BoxMap',lambda: chain.load_box_map(ROOT/'电控/deploy/sorting_config.ini'))
    probe('current-local-DropPoints',lambda: chain.load_drop_points(ROOT/'电控/deploy/sorting_config.ini'))
    converter=PixelToDeviceConverter(ROOT/'电控/calibration_config.ini')
    probe('current-local-calibration-status',lambda: (converter.is_calibrated,converter.object_heights))

run_probes()
(Path(__file__).parent/'gate-probes.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'PROBES: {len(rows)}, MATCHED: {sum(r["pass_"] for r in rows)}')
raise SystemExit(not all(r['pass_'] for r in rows))
