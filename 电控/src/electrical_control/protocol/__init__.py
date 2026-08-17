"""Public API for the protocol V0.4 frozen subset."""

from .codec import ProtocolCodec
from .direction import validate_direction
from .display_ack import (
    DisplayAckContextValidator,
    DisplayAckPayload,
    DisplayContent,
    crc32_iso_hdlc,
    decode_display_ack_payload,
    encode_display_ack_payload,
)
from .errors import (
    ContractNotFrozen,
    DirectionError,
    PayloadError,
    ProtocolError,
    ResultIdentityConflict,
    SuccessCountOverflow,
)
from .item_context import (
    ItemTaskPayload,
    RoundSuccessCounter,
    build_display_content,
    encode_item_task_payload,
    verify_counter_context,
)
from .types import (
    Command,
    Device,
    DisplayAckMessage,
    DisplayAckReceived,
    DomainEvent,
    Frame,
)

__all__ = [
    "Command",
    "ContractNotFrozen",
    "Device",
    "DirectionError",
    "DisplayAckContextValidator",
    "DisplayAckMessage",
    "DisplayAckPayload",
    "DisplayAckReceived",
    "DisplayContent",
    "DomainEvent",
    "Frame",
    "ItemTaskPayload",
    "PayloadError",
    "ProtocolCodec",
    "ProtocolError",
    "ResultIdentityConflict",
    "RoundSuccessCounter",
    "SuccessCountOverflow",
    "build_display_content",
    "crc32_iso_hdlc",
    "decode_display_ack_payload",
    "encode_display_ack_payload",
    "encode_item_task_payload",
    "validate_direction",
    "verify_counter_context",
]
