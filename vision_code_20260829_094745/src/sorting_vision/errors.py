"""Explicit, fail-closed errors used by the vision core."""


class VisionError(Exception):
    code = "VISION_ERROR"


class ConfigurationError(VisionError):
    code = "INVALID_CONFIGURATION"


class InvalidInputError(VisionError):
    code = "INVALID_INPUT"


class ModelUnavailableError(VisionError):
    code = "MODEL_UNAVAILABLE"


class DependencyUnavailableError(VisionError):
    code = "DEPENDENCY_UNAVAILABLE"


class BackendError(VisionError):
    code = "BACKEND_ERROR"


class InvalidDetectionError(VisionError):
    code = "INVALID_DETECTION"


class UnknownClassError(VisionError):
    code = "UNKNOWN_CLASS"


class CoordinateOutOfBoundsError(VisionError):
    code = "COORDINATE_OUT_OF_BOUNDS"


class DuplicateDetectionError(VisionError):
    code = "DUPLICATE_DETECTION"


class EmptyDetectionError(VisionError):
    code = "EMPTY_DETECTION"


class AmbiguousReacquireError(VisionError):
    code = "AMBIGUOUS_REACQUIRE"


class AmbiguousTargetError(VisionError):
    code = "AMBIGUOUS_TARGET"
