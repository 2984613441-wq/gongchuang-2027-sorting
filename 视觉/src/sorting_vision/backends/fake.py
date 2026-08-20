"""Deterministic backend for host-only tests without cameras or weights."""

from __future__ import annotations

from collections.abc import Mapping

from ..errors import InvalidInputError
from ..types import BackendOutput, FakeImage, ImageLike


class FakeBackend:
    name = "fake"

    def __init__(self, outputs: Mapping[str, BackendOutput]) -> None:
        self._outputs = dict(outputs)

    def infer(self, image: ImageLike) -> BackendOutput:
        if not isinstance(image, FakeImage):
            raise InvalidInputError("FakeBackend accepts only FakeImage test inputs")
        if image.corrupted:
            raise InvalidInputError(f"fake image {image.key!r} is marked as corrupted")
        if image.width <= 0 or image.height <= 0:
            raise InvalidInputError("fake image dimensions must be positive")
        try:
            output = self._outputs[image.key]
        except KeyError as exc:
            raise InvalidInputError(f"no fake output registered for image key {image.key!r}") from exc
        output.validate_dimensions()
        if (output.image_width, output.image_height) != (image.width, image.height):
            raise InvalidInputError("fake input dimensions do not match registered backend output")
        return output
