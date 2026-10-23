"""Bounded source and structure checks, never an assertion of factual truth."""
import re
import calendar
from decimal import Decimal

from .models import Report

MISSING = {"—", "未披露", "未单列", "未知", "不适用", "待确认"}
NUMBER = re.compile(r"(?<![\d.])[+-]?(?:\d{1,3}(?:[, \u00a0\u202f]\d{3})+|\d+)(?:\.\d+)?(?!\d|\.\d)")
MONTH_NAMES = {name.lower(): index for index in range(1, 13)
               for name in (calendar.month_name[index], calendar.month_abbr[index])}
MONTH_NAMES['sept'] = 9
ENGLISH_DATE = re.compile(r'\b(' + '|'.join(sorted(MONTH_NAMES, key=len, reverse=True))
    + r')\.?\s+(?:\d{4}\b|(?:[1-9]|[12]\d|3[01])(?:(?:st|nd|rd|th)\b|(?:,\s*|\s+)\d{4}\b))', re.I)


class EvidenceIssues(ValueError):
    def __init__(self, issues):
        self.issues = issues
        first = issues[0]
        super().__init__(f"{first['reason']}（位置 {first['path']}，共 {len(issues)} 项）")


def numeric_text(text: str):
    normalized = text.replace('−', '-').replace('，', ',')
    # PDF financial tables can join two negative, grouped two-decimal amounts.
    # Restrict this to explicit accounting amounts; ordinary 10-20 ranges stay unsigned.
    return re.sub(r'(-\d{1,3}(?:,\d{3})+\.\d{2})(?=-\d{1,3}(?:,\d{3})+\.\d{2}(?!\d))', r'\1 ', normalized)


def number_tokens(text: str):
    return [Decimal(re.sub(r'[, \u00a0\u202f]', '', x.group())) for x in NUMBER.finditer(numeric_text(text))]


def narrative_number_tokens(text: str):
    """Recognize prose-equivalent declines and unambiguous English date months."""
    normalized = numeric_text(text)
    values = []
    for match in NUMBER.finditer(normalized):
        value = Decimal(re.sub(r'[, \u00a0\u202f]', '', match.group()))
        prefix = normalized[max(0, match.start()-65):match.start()]
        suffix = normalized[match.end():match.end()+32]
        chinese_decline = re.search(r'(?:下降|下滑|下跌|减少|降低|亏损|负增长)\s*[约为达了]*\s*$', prefix)
        english_decline = re.search(r'\b(?:declined|decreased|fell|dropped|edged down|down)\s+(?:(?:by|at|an?|annual|rate|of|about|around|almost)\s+)*[$€£]?\s*$', prefix, re.I)
        english_magnitude = re.match(r'\s*(?:percent|%)\s+(?:(?:decline|decrease|drop)\b|(?:lower|less)\s+(?:than|compared\s+(?:with|to))\b)', suffix, re.I)
        if chinese_decline or english_decline or english_magnitude:
            value = -abs(value)
        values.append(value)
    # Prose may translate "October 28th" to "10月28日". Literal chart
    # values still use number_tokens, so this does not authorize new measurements.
    values.extend(Decimal(MONTH_NAMES[match[1].lower()]) for match in ENGLISH_DATE.finditer(normalized))
    return values


def period_in_quote(period: str, quote: str) -> bool:
    """Recognize equivalent date spelling without inventing finer date precision."""
    text = re.sub(r"\s+", "", quote)
    value = re.sub(r"\s+", "", period)
    if value in text:
        return True
    half = re.fullmatch(r"(\d{4})H([12])", value)
    if half:
        return bool(re.search(half[1] + r"年?" + ("上半年" if half[2] == "1" else "下半年"), text))
    month = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if month:
        return bool(re.search(month[1] + "年" + str(int(month[2])) + "月", text))
    quarter = re.fullmatch(r"(\d{4})Q([1-4])", value)
    if quarter:
        chinese = "一二三四"[int(quarter[2])-1]
        return bool(re.search(quarter[1] + r"年?第?[" + quarter[2] + chinese + r"]季度", text))
    return False


def validate_evidence(report: Report, content: str) -> None:
    from .editorial import validate_editorial
    from .analytical import validate_analytical, validate_reading
    validate_editorial(report)
    validate_reading(report, content)
    issues = []
    ids = [s.id for s in report.sources if s.id]
    if len(ids) != len(set(ids)):
        raise ValueError("来源编号不能重复。")

    def refs(values):
        if any(x not in ids for x in values):
            raise ValueError("图表引用了未登记的来源编号。")

    def check(value: str, quote: str, missing=False, path="", field="value"):
        if missing and value in MISSING and not quote:
            return
        if not quote or quote not in content:
            issues.append({"path": path, "fields": [field, "quote"], "value": value, "quote": quote, "reason": "关键数字的引文不在输入材料中"})
            return
        available = number_tokens(quote)
        # A chart may encode "down by 5%" as -5. Keep magnitude and precision
        # unchanged; a drop TO 5%, or a positive increase, never authorizes -5.
        available.extend(x for x in narrative_number_tokens(quote) if x < 0)
        if any(token not in available for token in number_tokens(value)):
            issues.append({"path": path, "fields": [field, "quote"], "value": value, "quote": quote, "reason": "图表或指标含有引文未提供的数字"})

    def metric(m, path):
        check(m.value, m.quote, path=path)
        refs(m.source_ids)

    if report.story:
        from .story import validate_story
        validate_story(report.story, report.sections, check, refs)
    if report.spatial:
        from .spatial import validate_spatial
        validate_spatial(report.spatial, report.sections, check, refs)

    if report.title_lines:
        normalize = lambda s: re.sub(r"[\s:：,，·—-]", "", s)
        if normalize("".join(report.title_lines)) != normalize(report.title):
            raise ValueError("封面分行必须保留完整标题。")
    for mi, m in enumerate(report.metrics):
        metric(m, f"/metrics/{mi}")
    for si, section in enumerate(report.sections):
        refs(section.source_ids)
        visuals = [(f"/sections/{si}/visuals/{vi}", v) for vi, v in enumerate(section.visuals)]
        if section.chart is not None:
            visuals.insert(0, (f"/sections/{si}/chart", section.chart))
        for path, visual in visuals:
            refs(visual.source_ids)
            if visual.kind in {"bar", "line"}:
                if not visual.points:
                    raise ValueError("图表缺少数据。")
                if visual.kind == "line" and len(visual.points) < 2:
                    raise ValueError("趋势图至少需要两个时点。")
                if not visual.unit:
                    raise ValueError("数字图表必须标注统一单位。")
                for pi, point in enumerate(visual.points):
                    check(format(point.value, ".15g"), point.quote, path=f"{path}/points/{pi}")
                    refs(point.source_ids)
            elif visual.kind == "qualified_dot":
                from .qualified import validate_qualified
                validate_qualified(visual, path, check, refs)
            elif visual.kind == "multiseries":
                if len(set(visual.categories)) != len(visual.categories) or any(not x.strip() for x in visual.categories):
                    raise ValueError("多序列图分类必须非空且不重复。")
                if len({s.label for s in visual.series}) != len(visual.series):
                    raise ValueError("多序列图的序列名称不能重复。")
                if visual.display == "line":
                    monthly = all(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", x) for x in visual.categories)
                    yearly = all(re.fullmatch(r"\d{4}", x) for x in visual.categories)
                    if not (monthly or yearly) or visual.categories != sorted(visual.categories) or len(visual.categories) < 3:
                        raise ValueError("多序列折线须有至少三个升序真实年月，两个时点用分组柱图。")
                for sj, series in enumerate(visual.series):
                    if len(series.points) != len(visual.categories):
                        raise ValueError("序列点数须与分类对齐，缺失位置用null而非0。")
                    if sum(p is not None for p in series.points) < (2 if visual.display == "line" else 1):
                        raise ValueError("序列缺少真实观察值。")
                    for pi, point in enumerate(series.points):
                        if point is None:
                            continue
                        if point.label != visual.categories[pi]:
                            raise ValueError("序列数据点标签必须与对应分类相同。")
                        check(format(point.value, ".15g"), point.quote, path=f"{path}/series/{sj}/points/{pi}")
                        refs(point.source_ids)
            elif visual.kind == "comparison":
                for ri, row in enumerate(visual.rows):
                    for endpoint in ("before", "after"):
                        point = getattr(row, endpoint)
                        check(format(point.value, ".15g"), point.quote, path=f"{path}/rows/{ri}/{endpoint}")
                        refs(point.source_ids)
            elif visual.kind == "flow":
                if not visual.steps:
                    raise ValueError("流程图缺少步骤。")
            elif visual.kind == "matrix":
                for column in visual.columns:
                    if column.direction != "none" and not column.comparison_note:
                        raise ValueError("矩阵比较方向必须说明可比口径和指标用途。")
                for ri, row in enumerate(visual.rows):
                    if len(row.cells) != len(visual.columns):
                        raise ValueError("矩阵每行的单元格数必须与列数一致。")
                    for ci, cell in enumerate(row.cells):
                        check(cell.value, cell.quote, missing=True, path=f"{path}/rows/{ri}/cells/{ci}")
                        refs(cell.source_ids)
            elif visual.kind == "targets":
                for ti, item in enumerate(visual.items):
                    check(item.baseline, item.quote, missing=True, path=f"{path}/items/{ti}", field="baseline")
                    check(item.target, item.quote, missing=True, path=f"{path}/items/{ti}", field="target")
                    refs(item.source_ids)
                    # Only scalar values have a computable direction. Missing/ranges remain textual.
                    plain = lambda s: re.fullmatch(r"[≤≥<>≈~]?\s*[+-]?\d[\d,]*(?:\.\d+)?", s.strip())
                    if plain(item.baseline) and plain(item.target):
                        baseline, target = number_tokens(item.baseline)[0], number_tokens(item.target)[0]
                        if (item.direction == "up" and target < baseline) or (item.direction == "down" and target > baseline):
                            raise ValueError("目标方向与现状、目标数值不一致。")
            elif visual.kind == "roadmap":
                if len(visual.periods) != len(set(visual.periods)):
                    raise ValueError("路线图时间列不能重复。")
                for ti, item in enumerate(visual.milestones):
                    if item.period not in visual.periods or (item.end_period and item.end_period not in visual.periods):
                        raise ValueError("路线图里程碑超出声明的时间列。")
                    if item.end_period and visual.periods.index(item.end_period) < visual.periods.index(item.period):
                        raise ValueError("路线图结束时间不能早于开始时间。")
                    check(item.label, item.quote, path=f"{path}/milestones/{ti}", field="label")
                    if not period_in_quote(item.period, item.quote) or (item.end_period and not period_in_quote(item.end_period, item.quote)):
                        issues.append({"path": f"{path}/milestones/{ti}", "fields": ["period", "end_period", "quote"], "value": item.period + " → " + item.end_period,
                                       "quote": item.quote, "reason": "时间精度或时间窗口没有原句依据"})
                        issues.append({"path": path, "fields": ["periods", "note"], "value": visual.periods,
                                       "quote": item.quote, "reason": "必要时增加原句支持的较粗时间列，不可把全年强行分到某个半年"})
                    refs(item.source_ids)
            elif visual.kind == "car":
                for mi, m in enumerate(visual.metrics):
                    metric(m, f"{path}/metrics/{mi}")
            elif visual.kind in ("contrast", "membership", "evidence_strip"):
                from .qualitative import validate_qualitative
                validate_qualitative(visual, path, check, refs)
            elif visual.kind in ("waterfall", "mechanism"):
                validate_analytical(visual, path, check, refs)
            elif visual.kind == "scatter":
                for pi, point in enumerate(visual.points):
                    for axis in ("x", "y"):
                        check(format(getattr(point, axis), ".15g"), point.quote, path=f"{path}/points/{pi}", field=axis)
                    refs(point.source_ids)
            elif visual.kind == "worldmap":
                countries = {"RUS": ("俄罗斯", "俄", "图拉"), "BRA": ("巴西",), "THA": ("泰国", "罗勇"), "AUS": ("澳大利亚", "澳洲", "澳新"), "ZAF": ("南非",), "CHN": ("中国", "国内")}
                if len({p.country for p in visual.places}) != len(visual.places):
                    raise ValueError("市场图同一国家只能登记一次。")
                for pi, place in enumerate(visual.places):
                    check(place.value, place.quote, path=f"{path}/places/{pi}")
                    refs(place.source_ids)
                    if not any(name in place.quote for name in countries[place.country]):
                        raise ValueError("市场图引文未说明对应的国家或市场。")
    for source in report.sources:
        if source.url and (not re.match(r"^https?://", source.url) or source.url not in content):
            raise ValueError("来源链接必须直接来自输入材料。")
        if source.date and source.date not in content:
            raise ValueError("来源日期必须来自输入材料，不可补造。")
    if issues:
        raise EvidenceIssues(issues)
