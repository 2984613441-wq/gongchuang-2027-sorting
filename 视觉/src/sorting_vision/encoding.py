"""Color and shape encoding for flexible bin assignment.

Encodes color and shape as a single byte for transmission to Raspberry Pi.
This allows bin mapping to be changed in Raspberry Pi config without reflashing MaixCAM.

Protocol:
    image_id = (color_code << 4) | shape_code

    High 4 bits: color (0-15)
    Low 4 bits: shape (0-15)
"""

from __future__ import annotations

# Color encoding (0-15)
COLOR_TO_CODE = {
    "red": 0,
    "orange": 1,
    "yellow": 2,
    "green": 3,
    "cyan": 4,
    "blue": 5,
    "purple": 6,
    "pink": 7,
    "black": 8,
    "white": 9,
    "gray": 10,
    "unknown": 15,  # Reserved for unknown colors
}

# Shape encoding (0-15)
SHAPE_TO_CODE = {
    "cube": 0,
    "cuboid": 1,
    "cylinder": 2,
    "sphere": 3,
    "hexagonal_prism": 4,
    "pentagonal_prism": 5,
    "square_pyramid": 6,
    "triangular_prism": 7,
    "regular_tetrahedron": 8,
    "unknown": 15,  # Reserved for unknown shapes
}

# Reverse mappings for decoding
CODE_TO_COLOR = {code: color for color, code in COLOR_TO_CODE.items()}
CODE_TO_SHAPE = {code: shape for shape, code in SHAPE_TO_CODE.items()}


def encode_color_shape(color: str, shape: str) -> int:
    """Encode color and shape into a single byte.

    Args:
        color: Color name (English, from color_quant).
        shape: Shape name (English, from YOLO or depth_fusion).

    Returns:
        Encoded byte (0-255): high 4 bits = color, low 4 bits = shape.

    Examples:
        >>> encode_color_shape("red", "cube")
        0  # (0 << 4) | 0
        >>> encode_color_shape("blue", "cylinder")
        82  # (5 << 4) | 2
    """
    color_code = COLOR_TO_CODE.get(color, 15)  # Default to "unknown"
    shape_code = SHAPE_TO_CODE.get(shape, 15)
    return (color_code << 4) | shape_code


def decode_color_shape(encoded: int) -> tuple[str, str]:
    """Decode a single byte into color and shape.

    Args:
        encoded: Encoded byte (0-255).

    Returns:
        (color, shape): Tuple of color and shape names.

    Examples:
        >>> decode_color_shape(0)
        ('red', 'cube')
        >>> decode_color_shape(82)
        ('blue', 'cylinder')
    """
    color_code = (encoded >> 4) & 0x0F
    shape_code = encoded & 0x0F

    color = CODE_TO_COLOR.get(color_code, "unknown")
    shape = CODE_TO_SHAPE.get(shape_code, "unknown")

    return color, shape


def validate_encoding() -> bool:
    """Validate that all color/shape combinations can be encoded/decoded.

    Returns:
        True if all combinations round-trip correctly.
    """
    for color in COLOR_TO_CODE:
        for shape in SHAPE_TO_CODE:
            encoded = encode_color_shape(color, shape)
            decoded_color, decoded_shape = decode_color_shape(encoded)

            if decoded_color != color or decoded_shape != shape:
                return False

    return True
