"""Scheme-B source/destination whitelist for the frozen critical commands."""

from .errors import DirectionError
from .types import Command, Device


_SCHEME_B_DIRECTIONS = {
    Command.BARRIER_READY: (Device.STM32, Device.RASPI),
    Command.MOTION_DONE: (Device.STM32, Device.RASPI),
    Command.ITEM_RESULT: (Device.STM32, Device.RASPI),
    Command.DISPLAY_ACK: (Device.RASPI, Device.STM32),
}


def validate_direction(command: Command, sender: Device, receiver: Device) -> None:
    expected = _SCHEME_B_DIRECTIONS.get(command)
    if expected is None or (sender, receiver) != expected:
        raise DirectionError(
            f"illegal Scheme-B direction for {command.name}: "
            f"{sender.name}->{receiver.name}"
        )
