"""Deterministic chart design recommendations derived from existing report data.

The recommender classifies data shape only.  It never calculates new values,
changes the report, or treats a visual recipe as evidence.
"""

from __future__ import annotations

import re
from typing import TypedDict

from .models import Report
from .editorial_skill import chart_skill_prompt


class ChartDesignDecision(TypedDict):
    section_index: int
    visual_index: int
    recipe: str
    reason: str
    caveat: str


CHART_DESIGN_RULES = """\
先识别数据形状，再选择图形；主题造型只能承载已有数量、时间、状态或关系。
- 先核对观察性质、单位、统计口径、公共分类和缺失位置，再判断是否存在共同尺度。
- 折线只用于至少三个升序真实 YYYY 或 YYYY-MM 时点；两个观察点用端点对照或并列时期柱，不暗示中间路径。
- 多序列必须共享单位、分类、统计口径和观察性质。缺失值保留为空并断线，不补零、不插值；4—5 条长序列优先同尺度小多图。
- 两个已观察快照的多个同单位指标可用哑铃图；实际、调查、预测和目标不得混成前后变化。
- 矩阵中不可比单元格保留原值但不参与热度或优劣编码；不同基期、币种或定义不得造共同尺度。
- 时间线只使用材料明确给出的时间；分布图只用于真实区间/档位，不把任意类别伪装成分布。
- 散点只显示两个变量的共同位置，不暗示因果；没有真实顺序的定性材料，按比较、归属、证据性质选择contrast、membership或evidence_strip，不强造阶段框图。
- 先写出要解释的问题，再选图：同单位两期变化用comparison哑铃；一个结果由精确增减构成用waterfall；已有业务依赖与状态用mechanism证据关系图；两个变量的共同位置用scatter；真实时序用line。普通条图只回答大小差异，不能代替机制和结构。
- 一节可由互补图组合解释“结果→结构→业务证据”，每图承担不同子问题，不用同一批数字重复堆图；没有流量数据不画桑基宽度，没有可加减关系不画增减桥。
- 不为炫酷绘制装饰性正弦、权重、比例、3D 体积或物理单位；任何几何编码都须能回到已有数据和证据。
定性图形同样按问题选，不需要编造数值：
- contrast：两个对象在相同维度上的定性差异或互补，例如身份与凭据、能力与授权、政策与落实。left_label/right_label明确对象，rows每行label比较维度、left/right各为label/detail/nature/quote/source_ids。nature=recorded材料记载、proposed建议、unresolved待验证。每侧独立连续原句，不能把缺失写成不存在。它没有数轴，不表示优劣、先后或变化幅度。
- membership：多个对象分别涉及哪些职责、条件或类别，用归属点阵表达交集。sets为2—6个材料明确的分类；items每项label/detail/relations，relation含set_index、relation(included明确涉及/excluded明确排除/unknown未明确)、quote、source_ids。只有原文明确排除才用excluded；未列出关系默认unknown，不能把沉默当排除。无热度、面积、得分、覆盖率和虚构的总分。
- evidence_strip：一个决策中哪些是材料记载、建议和待验证，用开放证据分栏。items为label/detail/nature/quote/source_ids，至少两种nature。每项连续原句支持其证据性质；unresolved必须有材料明确的不确定性依据，不能任意编造缺口。各栏等宽，并列非阶段，不画箭头或成熟度阶梯。
- 不以新图数量为目的。反复出现的定性矩阵/机制框图若分别在问差异、职责和确定性，就重新选图；真正依赖顺序才保留mechanism，复杂原值核对才保留matrix。全篇避免一种图形反复套用，也不为多样性牺牲语义。
- 精确区分“有联系”和“需要阶段图”：两个对象相互绑定、职责互补、生命周期不同，首先用contrast解释差异；上下文信号与决策规则的角色不同，也优先对照，不能因为存在联系就把它们排成阶段。只有读者必须理解真实委派/执行顺序时才用mechanism。
- 多个组件分别承担哪些分类职责时，优先membership点阵并在detail保留成熟度和限制；避免把“组件名称—职责”重复写成大段单元格。各集合关系必须有原文依据，未描述的格保留未明确，不能泛化成不具备能力。部署控制边界等多对象细节无法由分类归属充分解释时，保留紧凑matrix。
"""


def design_selection_prompt() -> str:
    """Return the reusable prompt fragment for data-shape-first chart selection."""
    return CHART_DESIGN_RULES + '\n' + chart_skill_prompt()


_YEAR = re.compile(r"^(\d{4})$")
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_QUARTER = re.compile(r"^(\d{4})[- ]?Q([1-4])$", re.I)
_HALF = re.compile(r"^(\d{4})[- ]?H([12])$", re.I)
_BIN = re.compile(
    r"^\s*(?:[<≤>≥]\s*)?-?\d+(?:\.\d+)?(?:\s*(?:[-–—~至]|to)\s*-?\d+(?:\.\d+)?)?\s*%?\s*$",
    re.I,
)


def _strict_time_key(label: str) -> tuple[int, int] | None:
    """Time key accepted for a continuous line by the current report contract."""
    value = label.strip()
    if match := _YEAR.fullmatch(value):
        return int(match.group(1)), 0
    if match := _MONTH.fullmatch(value):
        return int(match.group(1)), int(match.group(2))
    return None


def _period_key(label: str) -> tuple[int, int] | None:
    """Broader period recognition for paired columns and timelines."""
    if key := _strict_time_key(label):
        return key
    value = label.strip()
    if match := _QUARTER.fullmatch(value):
        return int(match.group(1)), int(match.group(2)) * 3
    if match := _HALF.fullmatch(value):
        return int(match.group(1)), int(match.group(2)) * 6
    return None


def _is_ordered_time(labels: list[str], *, strict: bool) -> bool:
    parser = _strict_time_key if strict else _period_key
    if strict and not (all(_YEAR.fullmatch(x.strip()) for x in labels) or all(_MONTH.fullmatch(x.strip()) for x in labels)):
        return False
    keys = [parser(label) for label in labels]
    return all(key is not None for key in keys) and keys == sorted(keys) and len(set(keys)) == len(keys)


def _looks_like_distribution(labels: list[str]) -> bool:
    if len(labels) < 3 or not all(_BIN.fullmatch(label) for label in labels):
        return False
    # A plain list of scalar category codes is not a distribution.
    return any(re.search(r"[<≤>≥–—~至]|\bto\b", label, re.I) for label in labels)


def _decision(section_index: int, visual_index: int, recipe: str, reason: str, caveat: str) -> ChartDesignDecision:
    return {
        "section_index": section_index,
        "visual_index": visual_index,
        "recipe": recipe,
        "reason": reason,
        "caveat": caveat,
    }


def _recommend_visual(section_index: int, visual_index: int, visual) -> ChartDesignDecision:
    kind = visual.kind
    if kind in ('contrast', 'membership', 'evidence_strip'):
        recipes = {'contrast': ('qualitative_pair', '两个对象按相同维度进行有证据的定性对照。'),
                   'membership': ('categorical_membership', '点阵显示对象与类别的归属及交集。'),
                   'evidence_strip': ('evidence_facets', '分栏区分材料记载、建议与待验证。')}
        recipe, reason = recipes[kind]
        return _decision(section_index, visual_index, recipe, reason,
                         '仅编码类别；没有数轴、权重、量化占比、先后或因果暗示。')

    if kind == 'waterfall':
        return _decision(section_index, visual_index, 'signed_result_bridge',
                         '起点、带符号的增减与终点形成可核对的闭合关系。',
                         '同一单位与统计口径；不补造残差或把期间差额当作因果贡献。')
    if kind == 'mechanism':
        return _decision(section_index, visual_index, 'evidence_relationship_map',
                         '材料支持节点间明确的关系与证据状态，适合按阶段和泳道解释。',
                         '箭头表示材料中声明的关系，线宽不表示流量；建议和缺口不画成已实现结果。')

    if kind == "qualified_dot":
        return _decision(section_index, visual_index, "qualified_dot", "同尺度保留近似值和单侧界限", "界限不是观测点，也不代表置信区间；不计算伪精确差值")
    if kind == "comparison":
        return _decision(
            section_index,
            visual_index,
            "snapshot_dumbbell",
            f"{len(visual.rows)} 个指标共享同一单位和一对前后端点，适合直接比较变化方向与幅度。",
            "只表示两个已观察快照，不连接或推断中间路径；端点必须保持各自证据。",
        )

    if kind == "multiseries":
        categories = list(visual.categories)
        missing = sum(point is None for series in visual.series for point in series.points)
        nature = {
            "observed": "统计观测",
            "survey": "调查读数",
            "forecast": "预测",
            "target": "目标",
        }[visual.observation]
        missing_note = f"共有 {missing} 个缺失位置，必须留空并断开，不得补零或插值。" if missing else ""
        scale_note = "共同尺度只以已声明的 unit、basis 和各序列 definition 为准，仍需逐项复核口径。"

        if len(categories) == 2 and _is_ordered_time(categories, strict=False):
            return _decision(
                section_index,
                visual_index,
                "paired_period_columns",
                f"{len(visual.series)} 个{nature}序列共享两个有序时期，适合并列端点而非趋势线。",
                f"两个时期不说明中间轨迹。{missing_note}{scale_note}",
            )

        if len(categories) >= 3 and _is_ordered_time(categories, strict=True):
            recipe = "small_multiples_trend" if len(visual.series) >= 4 else "multi_series_trend"
            reason = (
                f"{len(visual.series)} 个{nature}序列共享 {len(categories)} 个升序真实年月；"
                + ("序列较多，小多图可避免交叉拥挤。" if recipe == "small_multiples_trend" else "可在同一时间轴比较走势。")
            )
            return _decision(section_index, visual_index, recipe, reason, f"{missing_note}{scale_note}")

        return _decision(
            section_index,
            visual_index,
            "grouped_category_columns",
            f"{len(visual.series)} 个{nature}序列共享分类，但分类不是至少三个升序 YYYY 或 YYYY-MM 时点。",
            f"不得按连续时间绘制折线；按离散分类比较。{missing_note}{scale_note}",
        )

    if kind == "matrix":
        incomparable = sum(not cell.comparable for row in visual.rows for cell in row.cells)
        caveat = "不同单位或定义只在各自列内阅读，不计算总分或跨列共同尺度。"
        if incomparable:
            caveat = f"{incomparable} 个单元格标为不可比，须保留原值但排除热度、排序和优劣编码。" + caveat
        return _decision(
            section_index,
            visual_index,
            "comparison_matrix",
            f"{len(visual.rows)} 个对象横跨 {len(visual.columns)} 个维度，适合按行列检查口径和缺口。",
            caveat,
        )

    if kind == "roadmap":
        proposals = sum(item.status == "proposal" for item in visual.milestones)
        return _decision(
            section_index,
            visual_index,
            "timeline",
            f"{len(visual.milestones)} 个里程碑已绑定 {len(visual.periods)} 个材料内时期。",
            f"仅按明确时期定位；其中 {proposals} 项为建议或规划，视觉上必须与已发生事项区分。",
        )

    if kind == "targets":
        return _decision(
            section_index,
            visual_index,
            "target_gap_rows",
            f"{len(visual.items)} 项均含现状、目标和各自方向，适合逐项显示目标差距。",
            "各指标使用自己的单位和尺度；不计算完成率，也不把目标画成已实现结果。",
        )

    if kind == "scatter":
        return _decision(
            section_index,
            visual_index,
            "relationship_scatter",
            f"{len(visual.points)} 个对象各有一对数值，可在两个独立坐标轴上显示共同位置。",
            "直接标注对象和原值；参考线只用有业务含义的零值或实际样本中位数。区域说明不自动判优，不补造定性评分；两个坐标轴分别保留单位、期间与口径，相关位置不代表因果。",
        )

    if kind == "worldmap":
        return _decision(
            section_index,
            visual_index,
            "geographic_nodes",
            f"{len(visual.places)} 个材料明确提及的国家节点适合展示市场分布。",
            "节点不代表精确厂址；不同比例、币种或时期的 value 不以面积比较或汇总。",
        )

    if kind == "car":
        return _decision(
            section_index,
            visual_index,
            "semantic_evidence_object",
            f"{len(visual.metrics)} 个指标属于同一汽车实体，可挂接在有业务含义的部位。",
            "物件部位必须承载真实语义；指标仍按各自单位阅读，不用装饰造共同尺度。",
        )

    if kind == "flow":
        return _decision(
            section_index,
            visual_index,
            "sequence_flow",
            f"材料已提供 {len(visual.steps)} 项关系或条件，使用文字结构表达。",
            "箭头只表示材料明确的顺序或依赖；没有时滞、吞吐或反馈数据时不增加波形、权重或流量。",
        )

    if kind == "line":
        labels = [point.label for point in visual.points]
        if len(labels) >= 3 and _is_ordered_time(labels, strict=True):
            return _decision(
                section_index,
                visual_index,
                "single_series_trend",
                f"单一指标有 {len(labels)} 个升序真实年月观察值，可展示连续时间变化。",
                "仅连接真实观察值；缺期不得补点或平滑成额外数据。",
            )
        if len(labels) == 2 and _is_ordered_time(labels, strict=False):
            return _decision(
                section_index,
                visual_index,
                "paired_period_columns",
                "单一指标只有两个有序时期，适合端点并列。",
                "不得以折线暗示两个端点之间的路径。",
            )
        return _decision(
            section_index,
            visual_index,
            "categorical_points",
            "标签不构成至少三个升序真实年月，无法证明连续时间轴。",
            "必须降级为离散类别比较，不连接成趋势线。",
        )

    if kind == "bar":
        labels = [point.label for point in visual.points]
        if _looks_like_distribution(labels):
            return _decision(
                section_index,
                visual_index,
                "distribution_columns",
                f"{len(labels)} 个标签是明确数值区间或阈值档位，适合展示真实分布。",
                "区间顺序和宽度沿用原标签；没有样本量或密度依据时不改算占比或面积。",
            )
        return _decision(
            section_index,
            visual_index,
            "categorical_stem_plot",
            f"{len(labels)} 个同单位离散类别适合直接比较数值。",
            "类别不是连续时间或分布，不连接、不插值；单点应降级为指标读数。" if len(labels) == 1 else "只比较已声明的同单位数值，不增加排名含义。",
        )

    return _decision(
        section_index,
        visual_index,
        "evidence_text",
        "现有数据形状没有足够的定量、时间或拓扑编码支持专门图形。",
        "保留为正文或证据卡，不添加装饰性几何。",
    )


def recommend_design(report: Report) -> list[ChartDesignDecision]:
    """Classify each modern visual into a rendering recipe without mutation.

    ``visual_index`` indexes ``report.sections[section_index].visuals``.  The
    legacy ``Section.chart`` field is intentionally excluded because current
    generation requires it to be null and because ``-1`` sentinel indices are
    unsafe for downstream renderers.
    """
    return [
        _recommend_visual(section_index, visual_index, visual)
        for section_index, section in enumerate(report.sections)
        for visual_index, visual in enumerate(section.visuals)
    ]
