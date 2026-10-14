"""Single source of truth for the vision core's shared numeric constants.

Every value here was previously written as a bare literal in one or more
modules, or carries protocol/domain meaning that a reader should not have to
re-derive. The module is deliberately dependency-free (stdlib only) so that any
other ``sorting_vision`` module can import it without pulling in numpy, OpenCV
or a model runtime.

Provenance is recorded per value:

* ``PROTOCOL`` - frozen by ``docs/design/interface-contract.md`` (V0.9). Do not
  change without an authorized protocol revision.
* ``TUNABLE`` - an empirical default. It may be changed, but only together with
  the on-site evidence that justifies it.

Nothing in this module is calibrated hardware truth.
"""

from __future__ import annotations

# --- PROTOCOL: docs/design/interface-contract.md (V0.9) ---------------------

MAX_TASK_ID = 65535
"""``ITEM_TASK`` ``task_id`` is an unsigned 16-bit field, so the domain is
``[0, 65535]``. Mirrors the check in ``maixcam_deploy/v6_bridge.py`` and
``stage1_color_v6_send.py``, which both raise on ``task_id`` outside 0..65535.
"""

MAX_TARGET_SEQ = 255
"""``ITEM_TASK`` ``target_seq``/``target_count`` is an unsigned 8-bit field, so
the domain is ``[1, 255]``. 0 is not a valid target sequence number.
"""

COORDINATE_BOUND_MM10 = 1450
"""Half-extent of the working area in 0.1 mm units: ``|X|, |Y| <= 1450``
(+-145.0 mm), origin = device centre.

``interface-contract.md``:163-164 states that values with ``|value| > 1450``
are rejected by the STM32. This is the canonical definition **for the vision
core**; ``drop_table`` re-exports it under its historical name
``ITEM_TASK_COORD_LIMIT`` so the literal exists exactly once inside
``sorting_vision``.

It is not the only copy in the repository: the electro-control side keeps its
own at ``电控/src/electrical_control/protocol/item_context.py:101``
(``_ITEM_TASK_X_LIMIT = 1450``), with a cross-language check at
``电控/stm32_logic/tests/p3_cross_language_check.py``. Unifying those is a
cross-subsystem change and is out of scope here; the two values agree.
"""

# --- TUNABLE: detection limits ---------------------------------------------

MAX_DETECTIONS_SINGLE_TARGET = 100
"""Upper bound on post-processed detections in the single-target loop.

Must exceed 1. ``postprocess`` raises ``DUPLICATE_DETECTION`` for overlapping
same-class boxes before the single-target loop can raise ``AMBIGUOUS_TARGET``;
a limit of 1 would clamp a duplicate pair to ``DETECTION_LIMIT_EXCEEDED`` and
lose that error classification.
"""

DEFAULT_MAX_DETECTIONS_BATCH = 100
"""Upper bound on post-processed detections for a batch inference call."""

DEFAULT_CONFIDENCE_THRESHOLD = 0.50
"""Default detection confidence threshold for the batch pipeline.

Status: TUNABLE and NOT yet calibrated. It is the value ``InferenceConfig``
already shipped with. ``single_target.SingleTargetLoopConfig`` used a looser
0.35 default, which was inconsistent with this one; 2026-10-11 unified both on
0.50. That unification is a behaviour change for callers that relied on the
0.35 default: detections scoring in [0.35, 0.50) are now filtered out. It must
be re-validated on site against real lighting before the province round.
"""

DEFAULT_NMS_IOU_THRESHOLD = 0.45
"""IoU above which two same-class boxes are treated as duplicates by NMS."""

MIN_CONTOUR_AREA_PX = 100
"""Smallest contour area, in pixels, that the shape-feature fallback will
classify. Below this a colour mask is assumed to be noise rather than an item.

Provenance: this is the value the 2026-10-11 task brief specified. It does
**not** match the archive's gate, which is resolution-relative:
``stage1_contour_v3.py``:18-19,103 uses ``0.0015 .. 0.22`` of the frame area,
i.e. 153.6 .. 22528 px at its 320x320 frame. A fixed pixel value cannot
reproduce a relative gate on an arbitrary crop, so this is a deliberate
approximation for the ROI helper, not a ported constant.
"""

# --- PROTOCOL: model input size --------------------------------------------

DEFAULT_INPUT_WIDTH = 448
DEFAULT_INPUT_HEIGHT = 448
"""Frozen model input size (448x448).

``视觉/README.md``:20 records the 2026-08-25 freeze; ``TRAINING.md``:60 records
the MaixHub task 317458 package as 448x448. The two documents disagree on the
model family (YOLO11n vs YOLOv5s) - see the project conflict ledger - but they
agree on 448x448, which is the value used here.
"""
