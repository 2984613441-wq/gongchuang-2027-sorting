"""Compensating host-side cross-layer safety guard.

This package does not claim that restart or bounded deduplication are native
state-machine capabilities.  It composes the existing public layers and uses
their public emergency-stop event as the conservative lock action.
"""

from .control_flow import ControlFlowGuard, NodeRestarted

__all__ = ["ControlFlowGuard", "NodeRestarted"]
