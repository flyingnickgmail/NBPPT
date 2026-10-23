"""Evidence-led cover contract: refer to reviewed facts, never redraw invented data."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class CoverItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ref: str = Field(min_length=1, max_length=100)
    caption: str = Field(min_length=1, max_length=100)


class EditorialCover(BaseModel):
    model_config = ConfigDict(extra='forbid')
    layout: Literal['contrast', 'sequence', 'constellation']
    question: str = Field(min_length=1, max_length=60)
    selection_reason: str = Field(min_length=20, max_length=400)
    items: list[CoverItem] = Field(min_length=2, max_length=4)
    takeaway: str = Field(min_length=1, max_length=120)
    boundary: str = Field(min_length=1, max_length=240)
