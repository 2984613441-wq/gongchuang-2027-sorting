"""Host-side display view model and renderer abstraction (Raspberry Pi -> HDMI).

The Raspberry Pi only receives class IDs / image IDs over the wire; the
class_id -> name mapping lives on the local TF card (requirement summary 5.2:
only category ID / image ID are transmitted, never image files). Real HDMI
rendering is injected at deployment; host tests use FakeDisplayRenderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from electrical_control.protocol import DisplayContent
from electrical_control.rpi import ItemTaskContext, PendingRender


@dataclass(frozen=True, slots=True)
class DisplayViewModel:
    """Four competition-required display fields: seq / name / image / success total."""

    target_seq: int
    name: str
    image_id: int
    success_count: int
    result_code: int


def build_display_view(
    content: DisplayContent,
    names: Mapping[int, str],
    image_ids: Mapping[int, int] | None = None,
) -> DisplayViewModel:
    """Resolve a wire DisplayContent into a local DisplayViewModel.

    names maps class_id -> display name (the Raspberry Pi local TF card table).
    image_ids optionally overrides the displayed image; when absent (None) or
    when the class has no override, content.image_id is used. success_count and
    result_code pass through unchanged.
    """

    try:
        name = names[content.class_id]
    except KeyError:
        raise ValueError(
            f"class_id {content.class_id} 不在本地名称映射"
        ) from None
    image_id = content.image_id
    if image_ids is not None:
        try:
            image_id = image_ids[content.class_id]
        except KeyError:
            raise ValueError(
                f"class_id {content.class_id} 不在图片 ID 映射"
            ) from None
    return DisplayViewModel(
        target_seq=content.target_seq,
        name=name,
        image_id=image_id,
        success_count=content.success_count,
        result_code=content.result_code,
    )


class DisplayRenderer(Protocol):
    """Real HDMI rendering is injected at deployment; host uses FakeDisplayRenderer."""

    def present(self, view: DisplayViewModel) -> PendingRender: ...


class FakeDisplayRenderer:
    """Host-side fake: rebuilds a DisplayContent from the view for PendingRender.

    DisplayViewModel carries the resolved local name instead of class_id, so
    the class_id is recovered from the task payload given at construction time;
    the resulting PendingRender.complete() yields the RenderReceipt the
    scheduler needs for the competition display-then-next-item gate.
    """

    def __init__(self, task: ItemTaskContext) -> None:
        self._task = task

    def present(self, view: DisplayViewModel) -> PendingRender:
        content = DisplayContent(
            target_seq=view.target_seq,
            class_id=self._task.payload.class_id,
            image_id=view.image_id,
            success_count=view.success_count,
            result_code=view.result_code,
        )
        return PendingRender(content, self._task)


__all__ = [
    "DisplayRenderer",
    "DisplayViewModel",
    "FakeDisplayRenderer",
    "build_display_view",
]
