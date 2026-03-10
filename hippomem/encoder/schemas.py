"""
Pydantic schemas for encoder outputs.
"""
from dataclasses import dataclass


@dataclass
class EncodeResult:
    """
    Return value of encode().

    Attributes:
        turn_id: UUID linking this encode to its corresponding decode row.
    """
    turn_id: str
