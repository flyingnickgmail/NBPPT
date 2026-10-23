"""Report content contract. Legacy single-chart reports remain readable."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from .spatial_models import SpatialScene
from .editorial_models import EditorialCover
from .overview_models import OverviewImage


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Point(StrictModel):
    label: str = Field(max_length=100)
    value: float = Field(allow_inf_nan=False, ge=-1e15, le=1e15)
    quote: str = Field(min_length=1, max_length=1200)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class VisualBase(StrictModel):
    title: str = Field(max_length=200)
    note: str = Field(default="", max_length=1200)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    width: Literal["full", "half"] = "full"


class Chart(VisualBase):
    kind: Literal["none", "bar", "line", "flow"]
    unit: str = Field(max_length=40)
    points: list[Point] = Field(max_length=24)
    steps: list[str] = Field(max_length=12)


class Cell(StrictModel):
    value: str = Field(max_length=120)
    quote: str = Field(max_length=1200)
    source_ids: list[str] = Field(default_factory=list, max_length=5)
    comparable: bool = True


class Column(StrictModel):
    label: str = Field(min_length=1, max_length=80)
    unit: str = Field(max_length=40)
    direction: Literal["higher", "lower", "none"] = "none"
    comparison_note: str = Field(default="", max_length=300)


class MatrixRow(StrictModel):
    label: str = Field(min_length=1, max_length=100)
    cells: list[Cell] = Field(min_length=1, max_length=8)
    emphasis: bool = False


class Matrix(VisualBase):
    kind: Literal["matrix"]
    columns: list[Column] = Field(min_length=2, max_length=8)
    rows: list[MatrixRow] = Field(min_length=2, max_length=16)


class Target(StrictModel):
    label: str = Field(min_length=1, max_length=100)
    baseline: str = Field(max_length=80)
    target: str = Field(max_length=80)
    unit: str = Field(min_length=1, max_length=40)
    direction: Literal["up", "down", "neutral"]
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class Targets(VisualBase):
    kind: Literal["targets"]
    items: list[Target] = Field(min_length=1, max_length=16)


class Milestone(StrictModel):
    lane: str = Field(min_length=1, max_length=80)
    period: str = Field(min_length=1, max_length=60)
    end_period: str = Field(default="", max_length=60)
    label: str = Field(min_length=1, max_length=160)
    status: Literal["proposal", "observed"]
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class Roadmap(VisualBase):
    kind: Literal["roadmap"]
    periods: list[str] = Field(min_length=2, max_length=12)
    milestones: list[Milestone] = Field(min_length=1, max_length=40)


class Metric(StrictModel):
    label: str = Field(max_length=100)
    value: str = Field(max_length=80)
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class Car(VisualBase):
    kind: Literal["car"]
    metrics: list[Metric] = Field(min_length=1, max_length=6)


class ScatterPoint(StrictModel):
    label: str = Field(min_length=1, max_length=100)
    x: float = Field(allow_inf_nan=False, ge=-1e15, le=1e15)
    y: float = Field(allow_inf_nan=False, ge=-1e15, le=1e15)
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)
    emphasis: bool = False


class ScatterAnalysis(StrictModel):
    """Explain observed positions without generating scores or causal claims."""
    reference: Literal["none", "zero", "median"] = "none"
    x_low_label: str = Field(default="", max_length=40)
    x_high_label: str = Field(default="", max_length=40)
    y_low_label: str = Field(default="", max_length=40)
    y_high_label: str = Field(default="", max_length=40)
    emphasis_label: str = Field(default="", max_length=100)


class Scatter(VisualBase):
    kind: Literal["scatter"]
    x_label: str = Field(min_length=1, max_length=80)
    y_label: str = Field(min_length=1, max_length=80)
    x_unit: str = Field(min_length=1, max_length=40)
    y_unit: str = Field(min_length=1, max_length=40)
    points: list[ScatterPoint] = Field(min_length=2, max_length=16)
    analysis: ScatterAnalysis | None = None


class MapPlace(StrictModel):
    country: Literal["RUS", "BRA", "THA", "AUS", "ZAF", "CHN"]
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class Worldmap(VisualBase):
    kind: Literal["worldmap"]
    places: list[MapPlace] = Field(min_length=2, max_length=6)


class ComparisonRow(StrictModel):
    label: str = Field(min_length=1, max_length=100)
    before: Point
    after: Point


class Comparison(VisualBase):
    """Two observed snapshots, with independent provenance for each endpoint."""
    kind: Literal["comparison"]
    unit: str = Field(min_length=1, max_length=40)
    before_label: str = Field(min_length=1, max_length=80)
    after_label: str = Field(min_length=1, max_length=80)
    rows: list[ComparisonRow] = Field(min_length=1, max_length=12)


class QualifiedPoint(Point):
    relation: Literal["exact", "approx", "gt", "lt", "gte", "lte"]
    qualifier_quote: str = Field(min_length=1, max_length=180)
    emphasis: bool = False


class QualifiedDot(VisualBase):
    """Reported values and one-sided bounds, never fabricated error bars."""
    kind: Literal["qualified_dot"]
    unit: str = Field(min_length=1, max_length=40)
    basis: str = Field(min_length=8, max_length=500)
    points: list[QualifiedPoint] = Field(min_length=2, max_length=16)


class DataSeries(StrictModel):
    label: str = Field(min_length=1, max_length=80)
    definition: str = Field(min_length=1, max_length=300)
    points: list[Point | None] = Field(min_length=2, max_length=24)


class MultiSeries(VisualBase):
    kind: Literal["multiseries"]
    display: Literal["grouped_bar", "line"]
    unit: str = Field(min_length=1, max_length=40)
    categories: list[str] = Field(min_length=2, max_length=24)
    basis: str = Field(min_length=8, max_length=500)
    observation: Literal["observed", "survey", "forecast", "target"]
    series: list[DataSeries] = Field(min_length=2, max_length=5)


class Waterfall(VisualBase):
    kind: Literal["waterfall"]
    unit: str = Field(min_length=1, max_length=40)
    basis: str = Field(min_length=8, max_length=500)
    start: Point
    changes: list[Point] = Field(min_length=1, max_length=10)
    end: Point


class MechanismNode(StrictModel):
    label: str = Field(min_length=1, max_length=32)
    lane: int = Field(ge=0, le=2)
    stage: int = Field(ge=0, le=3)
    status: Literal["observed", "proposal", "unknown"]
    detail: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class MechanismLink(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    origin: int = Field(alias="from", ge=0, le=7)
    to: int = Field(ge=0, le=7)
    label: str = Field(min_length=1, max_length=32)
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class Mechanism(VisualBase):
    kind: Literal["mechanism"]
    lanes: list[str] = Field(min_length=1, max_length=3)
    nodes: list[MechanismNode] = Field(min_length=2, max_length=8)
    links: list[MechanismLink] = Field(min_length=1, max_length=10)


class QualitativeStatement(StrictModel):
    label: str = Field(min_length=1, max_length=32)
    detail: str = Field(min_length=1, max_length=180)
    nature: Literal["recorded", "proposed", "unresolved"]
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class ContrastRow(StrictModel):
    label: str = Field(min_length=1, max_length=20)
    left: QualitativeStatement
    right: QualitativeStatement


class Contrast(VisualBase):
    kind: Literal["contrast"]
    left_label: str = Field(min_length=1, max_length=28)
    right_label: str = Field(min_length=1, max_length=28)
    rows: list[ContrastRow] = Field(min_length=2, max_length=6)


class MembershipRelation(StrictModel):
    set_index: int = Field(ge=0, le=5)
    relation: Literal["included", "excluded", "unknown"]
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class MembershipItem(StrictModel):
    label: str = Field(min_length=1, max_length=28)
    detail: str = Field(min_length=1, max_length=160)
    relations: list[MembershipRelation] = Field(min_length=1, max_length=6)


class Membership(VisualBase):
    kind: Literal["membership"]
    sets: list[str] = Field(min_length=2, max_length=6)
    items: list[MembershipItem] = Field(min_length=2, max_length=10)


class EvidenceStrip(VisualBase):
    kind: Literal["evidence_strip"]
    items: list[QualitativeStatement] = Field(min_length=3, max_length=9)


Visual = Chart | Matrix | Targets | Roadmap | Car | Scatter | Worldmap | Comparison | QualifiedDot | MultiSeries | Waterfall | Mechanism | Contrast | Membership | EvidenceStrip


class ReadingStep(StrictModel):
    title: str = Field(min_length=1, max_length=48)
    explanation: str = Field(min_length=1, max_length=300)
    visual_index: int = Field(ge=0, le=5)
    item_indices: list[int] = Field(min_length=1, max_length=10)
    paragraph_index: int = Field(ge=0, le=19)


class ReadingGuide(StrictModel):
    question: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=1, max_length=500)
    steps: list[ReadingStep] = Field(min_length=2, max_length=4)


class Section(StrictModel):
    label: str = Field(max_length=60)
    title: str = Field(min_length=1, max_length=200)
    paragraphs: list[str] = Field(max_length=20)
    bullets: list[str] = Field(max_length=20)
    chart: Chart | None = None
    visuals: list[Visual] = Field(default_factory=list, max_length=6)
    layout: Literal["editorial", "split", "feature"] = "editorial"
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    reading: ReadingGuide | None = None


class Source(StrictModel):
    label: str = Field(min_length=1, max_length=160)
    url: str = Field(max_length=2000)
    id: str = Field(default="", max_length=40)
    date: str = Field(default="", max_length=80)
    category: str = Field(default="", max_length=80)
    version: str = Field(default="", max_length=80)


class GlyphPart(StrictModel):
    """A bounded vector drawing instruction, never executable SVG/HTML."""
    kind: Literal["rect", "ellipse", "path"]
    x: float = Field(ge=0, le=160)
    y: float = Field(ge=0, le=160)
    width: float = Field(ge=0, le=160)
    height: float = Field(ge=0, le=160)
    path: str = Field(default="", max_length=600)
    fill: Literal["paper", "teal", "clay", "gold", "ink", "mist", "none"]
    stroke: Literal["paper", "teal", "clay", "gold", "ink", "mist", "none"]
    group: str = Field(default="body", pattern=r"^[a-z][a-z0-9_]{0,23}$")
    surface: Literal["flat", "metal", "glass", "paper"] = "flat"
    stroke_width: float = Field(default=1, ge=0, le=3)


class SceneAssembly(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    label: str = Field(min_length=1, max_length=30)
    dx: float = Field(ge=-35, le=35)
    dy: float = Field(ge=-35, le=35)
    angle: float = Field(ge=-30, le=30)
    pivot_x: float = Field(default=80, ge=0, le=160)
    pivot_y: float = Field(default=80, ge=0, le=160)


class SceneAction(StrictModel):
    object_id: str
    group: str
    effect: Literal["reveal", "trace", "turn", "slide"]
    reason: str = Field(min_length=1, max_length=120)


class SceneObject(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    label: str = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1, max_length=160)
    x: float = Field(ge=110, le=890)
    y: float = Field(ge=100, le=450)
    parts: list[GlyphPart] = Field(min_length=3, max_length=28)
    form: Literal["artifact", "instrument", "mechanism", "organic", "network", "architecture"] = "artifact"
    rationale: str = Field(default="", max_length=240)
    assemblies: list[SceneAssembly] = Field(default_factory=list, max_length=6)
    fact: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class SceneLink(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    origin: str
    destination: str
    label: str = Field(min_length=1, max_length=60)
    relation: Literal["context", "mechanism", "uncertain"]
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class SceneBeat(StrictModel):
    section_index: int = Field(ge=0, le=23)
    title: str = Field(min_length=1, max_length=36)
    caption: str = Field(min_length=1, max_length=240)
    focus: list[str] = Field(min_length=1, max_length=6)
    links: list[str] = Field(default_factory=list, max_length=8)
    composition: Literal["gather", "unfold", "balance"]
    actions: list[SceneAction] = Field(default_factory=list, max_length=8)
    quote: str = Field(min_length=1, max_length=1600)
    source_ids: list[str] = Field(default_factory=list, max_length=8)


class NarrativeScene(StrictModel):
    edition: Literal["classic", "semantic"] = "classic"
    title: str = Field(min_length=1, max_length=60)
    concept: str = Field(min_length=1, max_length=400)
    objects: list[SceneObject] = Field(min_length=3, max_length=6)
    links: list[SceneLink] = Field(default_factory=list, max_length=8)
    beats: list[SceneBeat] = Field(min_length=1, max_length=24)


class StoryDesign(StrictModel):
    story: NarrativeScene


class Report(StrictModel):
    title: str = Field(min_length=1, max_length=180)
    title_lines: list[str] = Field(default_factory=list, max_length=3)
    cover_style: Literal["auto", "geometric", "automotive"] = "auto"
    illustration: Literal["none", "economy", "technology", "ecology"] = "none"
    story: NarrativeScene | None = None
    spatial: SpatialScene | None = None
    editorial: EditorialCover | None = None
    subtitle: str = Field(max_length=300)
    summary: str = Field(max_length=1500)
    metrics: list[Metric] = Field(max_length=6)
    sections: list[Section] = Field(min_length=1, max_length=24)
    sources: list[Source] = Field(max_length=60)


class GenerateInput(StrictModel):
    content: str = Field(min_length=1, max_length=60000)
    title: str = Field(default="", max_length=180)
    mode: Literal["local", "ai"] = "local"
    theme: Literal["paper", "night"] = "paper"


class ExportInput(StrictModel):
    report: Report
    overview: OverviewImage | None = None
    content: str = Field(max_length=60000)
    theme: Literal["paper", "night"] = "paper"
    mode: Literal["local", "ai", "import"] = "import"
