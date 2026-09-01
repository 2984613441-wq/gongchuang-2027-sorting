"""Backend contract shared by PC, Raspberry Pi, and MaixCAM adapters."""

from __future__ import annotations

from typing import Protocol

from ..types import BackendOutput, ImageLike


class InferenceBackend(Protocol):
    @property
    def name(self) -> str: ...

    def infer(self, image: ImageLike) -> BackendOutput: ...
