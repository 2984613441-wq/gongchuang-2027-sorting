"""Stateless mapping from abstract frames to direction-checked messages."""

from .direction import validate_direction
from .display_ack import parse_display_ack_payload
from .errors import ContractNotFrozen
from .types import Command, DisplayAckMessage, Frame


class ProtocolCodec:
    """Decode only message payloads whose V0.4 wire contract is frozen."""

    def to_validated_message(self, frame: Frame) -> DisplayAckMessage:
        validate_direction(frame.command, frame.sender, frame.receiver)
        if frame.command is not Command.DISPLAY_ACK:
            raise ContractNotFrozen(
                f"payload for {frame.command.name} is not frozen in this batch"
            )
        parsed = parse_display_ack_payload(frame.payload)
        return DisplayAckMessage(
            task_id=frame.task_id,
            frame_seq=frame.frame_seq,
            target_seq=parsed.target_seq,
            render_result=parsed.render_result,
            content_crc32=parsed.content_crc32,
        )
