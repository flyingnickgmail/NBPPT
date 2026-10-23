"""Reusable editorial checks. Passing is not external fact verification."""
from collections import Counter
import re

from .evidence import narrative_number_tokens, number_tokens, validate_evidence
from .models import Report


def review_report(report: Report, content: str) -> dict:
    validate_evidence(report, content)
    material_numbers = set(number_tokens(content)) | set(narrative_number_tokens(content))
    findings = []
    if report.spatial:
        for beat in report.spatial.beats:
            if re.search(r'物体|图形|构图|不模拟|不编码|让读者看到', beat.caption):
                findings.append({'code': 'spatial_caption_process', 'section': beat.section_index,
                                 'detail': '随文旁注应解释研究判断；图形制作与表达边界放在构图说明。'})
    for field in ('title', 'subtitle', 'summary'):
        missing = sorted(set(narrative_number_tokens(getattr(report, field))) - material_numbers)
        if missing:
            findings.append({'code': 'headline_numbers', 'section': None, 'detail': f'{field}数值未在材料中找到：{", ".join(str(n) for n in missing[:6])}。'})
    visuals = [v for s in report.sections for v in ([s.chart] if s.chart and s.chart.kind != 'none' else []) + s.visuals]
    for i, section in enumerate(report.sections):
        text = '\n'.join(section.paragraphs + section.bullets)
        missing = sorted(set(narrative_number_tokens(text)) - material_numbers)
        if missing:
            findings.append({'code': 'body_numbers', 'section': i, 'detail': f'正文数值未在材料中找到：{", ".join(str(n) for n in missing[:6])}；需核查计算或改写。'})
        if number_tokens(text) and not section.source_ids:
            findings.append({'code': 'section_sources', 'section': i, 'detail': '本节有数字，但尚未绑定章节来源。'})
        if re.search(r'\d十亿美元', text):
            findings.append({'code': 'unit_expression', 'section': i, 'detail': '美元大单位的中文表达生硬；保留原数字，可改为“以十亿美元计，数值为…”，不换算。'})
    titles = Counter(v.title for v in visuals)
    for i, section in enumerate(report.sections):
        for v in ([section.chart] if section.chart else []) + section.visuals:
            if v.kind == 'bar' and len(v.points) == 1:
                findings.append({'code': 'single_point_chart', 'section': i, 'detail': f'「{v.title}」只有一个值，缺少比较关系；宜放入指标或有口径说明的证据表。'})
            if re.search(r'原文符号|为了通过检查|schema|无法画图', v.note, re.I):
                findings.append({'code': 'production_language', 'section': i, 'detail': f'「{v.title}」图注夹入了制作过程，需改为读者需要的统计含义。'})
    if any(n > 1 for n in titles.values()):
        findings.append({'code': 'duplicate_titles', 'section': None, 'detail': '存在同名图表，需确认是否表达重复。'})
    long_material = len(content) >= 12000
    multi = sum(len(s.visuals) + bool(s.chart and s.chart.kind != 'none') >= 2 for s in report.sections)
    prose_chars = sum(len(p) for s in report.sections for p in s.paragraphs + s.bullets)
    if long_material and prose_chars < 1800:
        findings.append({'code': 'thin_analysis', 'section': None, 'detail': '长材料正文偏短，需检查是否遗漏主要分析链、限制或建议依据。'})
    return {'version': 'report-quality.v1', 'status': 'needs_review' if findings else 'checks_passed',
            'findings': findings, 'stats': {'sections': len(report.sections), 'visuals': len(visuals), 'multi_visual_sections': multi, 'prose_chars': prose_chars},
            'limit': '检查范围为结构、引文、数值出现、来源绑定与表达覆盖；不证明事实真实、口径可比或论证成立。'}
