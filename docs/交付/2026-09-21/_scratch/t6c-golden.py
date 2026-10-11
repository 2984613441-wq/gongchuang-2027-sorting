"""临时（T6c）：用**补丁前的旧实现**算 6 组 golden sha256，供测试文件冻存。"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_ROOT / "电控" / "src"))
sys.path.insert(0, str(_ROOT / "电控" / "tools"))

from PIL import Image  # noqa: E402

from fb_encode_parity import PATTERN, legacy_encode_frame  # noqa: E402
from electrical_control.rpi.display_hdmi import FramebufferFormat  # noqa: E402

CASES = ((16, None), (16, 2100), (24, None), (24, 3136), (32, None), (32, 4160))

frame = Image.fromarray(PATTERN, "RGB")
for bpp, ll in CASES:
    data = legacy_encode_frame(frame, FramebufferFormat(bpp, 1024, 600, line_length=ll))
    print(f'        ({bpp}, {ll}): "{hashlib.sha256(data).hexdigest()}",  # {len(data)} B')
