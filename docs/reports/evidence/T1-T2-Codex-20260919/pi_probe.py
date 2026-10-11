"""Offline only: reuse existing pure gateway fixtures; never open UART."""
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(root/'电控/src'), str(root/'电控/tests/rpi')]
from test_gateway import unlocked_scheduler, stm32_frame
from electrical_control.rpi.gateway import PiProtocolGateway
from electrical_control.protocol import Command
s = unlocked_scheduler()
g = PiProtocolGateway(s)
f = stm32_frame(Command.ACK, payload=bytes((0, 3)))
for label in ('first_ACK', 'replayed_ACK', 'second_replay'):
    out = g.feed_frame(f)
    print(f'{label} event={out.event} outbound={out.outbound} state={s.state.name}')
assert out.event == 'DUPLICATE' and out.outbound is None
print('PI_PROBE PASS: DUPLICATE is inbound identity dedup, not proof of a lost first ACK')
