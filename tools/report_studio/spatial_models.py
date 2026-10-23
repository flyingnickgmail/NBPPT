"""Bounded spatial design data. No generated JavaScript, shaders or external assets."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field

Coordinate = Annotated[float, Field(ge=-12, le=12, allow_inf_nan=False)]
Dimension = Annotated[float, Field(ge=.02, le=16, allow_inf_nan=False)]
Angle = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]


class SpatialModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SpacePart(SpatialModel):
    group: str
    shape: Literal['box', 'rounded_box', 'loft', 'lathe', 'arc', 'cylinder', 'ring', 'ellipsoid', 'prism']
    center: list[Coordinate] = Field(min_length=3, max_length=3)
    size: list[Dimension] = Field(min_length=3, max_length=3)
    rotation: list[Angle] = Field(min_length=3, max_length=3, description='XYZ Euler rotation in DEGREES, not radians. A quarter-turn is 90, never 1.5708.')
    profile: list[list[Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]]] = Field(default_factory=list, max_length=16)
    stations: list[list[Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]]] = Field(default_factory=list, max_length=12, description='Loft cross sections [x, half_width_y, bottom_z, top_z], normalized -1..1; strictly increasing x. Other shapes use [].')
    material: Literal['metal', 'ceramic', 'glass', 'paper', 'fiber', 'rubber']
    tone: Literal['ink', 'accent', 'blue', 'silver', 'chalk', 'copper']
    detail: Literal['none', 'ribs', 'grid', 'seam'] = 'none'
    sweep: Annotated[float, Field(ge=30, le=360, allow_inf_nan=False)] = 270


class SpaceGroup(SpatialModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,23}$')
    label: str = Field(min_length=1, max_length=16)
    rationale: str = Field(min_length=1, max_length=240)
    explode: list[Coordinate] = Field(min_length=3, max_length=3)
    fact: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class SpaceBeat(SpatialModel):
    section_index: int = Field(ge=0, le=23)
    title: str = Field(min_length=1, max_length=36)
    caption: str = Field(min_length=1, max_length=240)
    focus: list[str] = Field(min_length=1, max_length=3)
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class VisualOption(SpatialModel):
    expression: Literal['literal', 'relationship', 'editorial_metaphor']
    concept: str = Field(min_length=1, max_length=180)
    relevance: str = Field(min_length=1, max_length=240)
    risk: str = Field(min_length=1, max_length=180)


class VisualSelection(SpatialModel):
    question: str = Field(min_length=1, max_length=160)
    options: list[VisualOption] = Field(min_length=3, max_length=3)
    selected: int = Field(ge=0, le=2)
    reason: str = Field(min_length=1, max_length=240)


class SpatialScene(SpatialModel):
    title: str = Field(min_length=1, max_length=40)
    concept: str = Field(min_length=1, max_length=400)
    groups: list[SpaceGroup] = Field(min_length=2, max_length=5)
    parts: list[SpacePart] = Field(min_length=4, max_length=72)
    beats: list[SpaceBeat] = Field(min_length=1, max_length=24)
    selection: VisualSelection | None = None
    opening: list[str] = Field(default_factory=list, max_length=5)


class SpatialDesign(SpatialModel):
    spatial: SpatialScene
