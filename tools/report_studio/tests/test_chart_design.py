import json

from tools.report_studio.chart_design import CHART_DESIGN_RULES, design_selection_prompt, recommend_design
from tools.report_studio.models import Chart, Comparison, Matrix, MultiSeries, Point, Report, Section


def point(label, value):
    return Point(label=label, value=value, quote=f"{label} {value}", source_ids=[])


def report_with(*visuals):
    return Report(
        title="测试报告",
        subtitle="",
        summary="",
        metrics=[],
        sections=[Section(label="数据", title="数据", paragraphs=[], bullets=[], chart=None, visuals=list(visuals))],
        sources=[],
    )


def multiseries(categories, series_count=2, *, display="line", missing=False, definitions=None):
    definitions = definitions or [f"口径 {index}" for index in range(series_count)]
    series = []
    for index in range(series_count):
        points = [point(label, index + offset + 1) for offset, label in enumerate(categories)]
        if missing:
            points[-1] = None
        series.append({"label": f"序列 {index}", "definition": definitions[index], "points": points})
    return MultiSeries(
        kind="multiseries",
        title="多序列",
        display=display,
        unit="%",
        categories=categories,
        basis="同一单位与公共分类，具体定义逐项列示",
        observation="observed",
        series=series,
    )


def test_two_observations_are_paired_columns_not_a_trend():
    visual = Chart(
        kind="line",
        title="两个观察点",
        unit="%",
        points=[point("2024", 2), point("2025", 3)],
        steps=[],
    )
    decision = recommend_design(report_with(visual))[0]
    assert decision["recipe"] == "paired_period_columns"
    assert "不得以折线" in decision["caveat"]


def test_multi_metric_two_snapshot_comparison_selects_dumbbell():
    visual = Comparison(
        kind="comparison",
        title="前后快照",
        unit="%",
        before_label="2024",
        after_label="2025",
        rows=[
            {"label": "甲", "before": point("2024", 2), "after": point("2025", 3)},
            {"label": "乙", "before": point("2024", 4), "after": point("2025", 5)},
        ],
    )
    decision = recommend_design(report_with(visual))[0]
    assert decision["recipe"] == "snapshot_dumbbell"
    assert "不连接或推断中间路径" in decision["caveat"]


def test_real_ordered_time_selects_trend_and_preserves_missing_gaps():
    visual = multiseries(["2023", "2024", "2025"], missing=True)
    decision = recommend_design(report_with(visual))[0]
    assert decision["recipe"] == "multi_series_trend"
    assert "缺失" in decision["caveat"]
    assert "补零" in decision["caveat"]


def test_four_long_series_select_small_multiples():
    visual = multiseries(["2022", "2023", "2024", "2025"], series_count=4)
    assert recommend_design(report_with(visual))[0]["recipe"] == "small_multiples_trend"


def test_non_time_categories_cannot_become_line_or_common_time_scale():
    visual = multiseries(
        ["食品", "能源", "住房"],
        definitions=["CPI 同比", "PCE 年化"],
    )
    decision = recommend_design(report_with(visual))[0]
    assert decision["recipe"] == "grouped_category_columns"
    assert "不得按连续时间" in decision["caveat"]
    assert "共同尺度" in decision["caveat"]


def test_period_labels_allow_paired_columns_but_quarters_do_not_fake_a_long_line():
    paired = multiseries(["2024Q4", "2025Q1"], display="grouped_bar")
    assert recommend_design(report_with(paired))[0]["recipe"] == "paired_period_columns"
    three_quarters = multiseries(["2024Q3", "2024Q4", "2025Q1"])
    decision = recommend_design(report_with(three_quarters))[0]
    assert decision["recipe"] == "grouped_category_columns"
    assert "YYYY" in decision["reason"]


def test_distribution_requires_real_interval_labels():
    distribution = Chart(
        kind="bar",
        title="分布",
        unit="人",
        points=[point("0–10", 3), point("10–20", 4), point("≥20", 2)],
        steps=[],
    )
    categories = distribution.model_copy(
        update={"points": [point("甲", 3), point("乙", 4), point("丙", 2)]}
    )
    assert recommend_design(report_with(distribution))[0]["recipe"] == "distribution_columns"
    assert recommend_design(report_with(categories))[0]["recipe"] == "categorical_stem_plot"


def test_matrix_keeps_incomparable_cells_out_of_heat_encoding():
    visual = Matrix(
        kind="matrix",
        title="口径矩阵",
        columns=[
            {"label": "利润", "unit": "%", "direction": "higher", "comparison_note": "仅同口径比较"},
            {"label": "说明", "unit": "", "direction": "none"},
        ],
        rows=[
            {
                "label": "甲",
                "cells": [
                    {"value": "2", "quote": "甲2", "comparable": True},
                    {"value": "核心利润", "quote": "核心利润", "comparable": False},
                ],
            },
            {
                "label": "乙",
                "cells": [
                    {"value": "3", "quote": "乙3", "comparable": True},
                    {"value": "归母利润", "quote": "归母利润", "comparable": False},
                ],
            },
        ],
    )
    decision = recommend_design(report_with(visual))[0]
    assert decision["recipe"] == "comparison_matrix"
    assert "2 个单元格标为不可比" in decision["caveat"]
    assert "排除热度" in decision["caveat"]


def test_recommendations_are_json_serializable_and_do_not_mutate_report():
    report = report_with(multiseries(["2023-01", "2023-02", "2023-03"]))
    before = report.model_dump()
    decisions = recommend_design(report)
    json.dumps(decisions, ensure_ascii=False)
    assert report.model_dump() == before
    assert set(decisions[0]) == {"section_index", "visual_index", "recipe", "reason", "caveat"}
    assert design_selection_prompt().startswith(CHART_DESIGN_RULES)
    assert "不补零" in CHART_DESIGN_RULES
    assert "装饰性正弦" in CHART_DESIGN_RULES


def test_mixed_year_month_granularity_is_not_a_trend():
    visual = multiseries(['2023', '2024-01', '2025-01'], display='grouped_bar')
    assert recommend_design(report_with(visual))[0]['recipe'] == 'grouped_category_columns'
