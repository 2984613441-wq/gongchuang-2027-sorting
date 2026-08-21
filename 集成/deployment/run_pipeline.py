"""Raspberry Pi deployment entry for the JSONL vision-to-STM32 chain.

This is a thin wrapper around 集成/demo_bridge/action_bridge.py so the
Raspberry Pi start command does not need to know the module layout. All real
serial motion still requires --allow-motion and an enabled action config.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEMO_BRIDGE = ROOT / "集成" / "demo_bridge"
if str(DEMO_BRIDGE) not in sys.path:
    sys.path.insert(0, str(DEMO_BRIDGE))


def main(argv: Optional[list[str]] = None) -> int:
    import action_bridge

    return action_bridge.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
