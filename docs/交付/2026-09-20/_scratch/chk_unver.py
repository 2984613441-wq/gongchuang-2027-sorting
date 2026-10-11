import sys
sys.path.insert(0, 'src')
from electrical_control.pick_strategy.config import build_config
cfg = build_config('deploy/pick_strategy.ini')
u = cfg.unverified_params()
print("unverified_params() 共", len(u), "项:")
for x in u:
    print("   -", x)
print()
print("selection_mode =", cfg.selection_mode)
print("tray.open_side =", getattr(cfg.tray, "open_side", "?"))
