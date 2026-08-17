"""Errors raised by the frozen subset of protocol V0.4."""


class ProtocolError(ValueError):
    """Base error for rejected protocol input."""


class DirectionError(ProtocolError):
    """A command arrived from an illegal source/destination pair."""


class PayloadError(ProtocolError):
    """A payload is malformed or does not match the active context."""


class ContractNotFrozen(ProtocolError):
    """The requested wire behavior is not frozen by the current contract."""


class SuccessCountOverflow(ProtocolError):
    """A successful result would exceed the frozen one-byte round counter."""


class ResultIdentityConflict(ProtocolError):
    """The same result identity was observed with a different result code."""
