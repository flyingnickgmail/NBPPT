"""Semantic boundaries for result bridges and evidence relationship maps."""
from decimal import Decimal


def item_count(visual):
    if visual.kind == 'waterfall':
        return len(visual.changes) + 2
    for field in ('nodes', 'points', 'rows', 'items', 'milestones', 'series', 'metrics', 'places', 'steps'):
        if hasattr(visual, field):
            return len(getattr(visual, field))
    return 0


def validate_analytical(visual, path, check, refs):
    if visual.kind == 'waterfall':
        for name, point in [('start', visual.start), *[(f'changes/{i}', p) for i,p in enumerate(visual.changes)], ('end', visual.end)]:
            check(str(point.value), point.quote, path=f'{path}/{name}', field='value')
            refs(point.source_ids)
        total = Decimal(str(visual.start.value)) + sum((Decimal(str(p.value)) for p in visual.changes), Decimal(0))
        if abs(total - Decimal(str(visual.end.value))) > Decimal('0.01'):
            raise ValueError('增减桥不闭合：起点加全部增减项必须等于终点（原单位容差0.01）；不得编造平衡项。')
    elif visual.kind == 'mechanism':
        for i,node in enumerate(visual.nodes):
            if node.lane >= len(visual.lanes):
                raise ValueError('关系图节点泳道无效。')
            check(node.label+' '+node.detail, node.quote, path=f'{path}/nodes/{i}', field='detail')
            refs(node.source_ids)
        edges = set()
        for i,link in enumerate(visual.links):
            if max(link.origin,link.to) >= len(visual.nodes) or link.origin == link.to:
                raise ValueError('关系图连线必须引用两个已有节点。')
            if visual.nodes[link.origin].stage >= visual.nodes[link.to].stage:
                raise ValueError('关系图箭头必须指向更后的阶段；并列项不能伪装成因果链。')
            if (link.origin,link.to) in edges:
                raise ValueError('关系图重复连线。')
            edges.add((link.origin,link.to))
            check(link.label, link.quote, path=f'{path}/links/{i}', field='label')
            refs(link.source_ids)


def validate_reading(report, content):
    from .evidence import number_tokens, narrative_number_tokens
    allowed=set(number_tokens(content))|set(narrative_number_tokens(content))
    for section in report.sections:
        if not section.reading:
            continue
        guide=section.reading
        for step in guide.steps:
            if step.visual_index >= len(section.visuals) or step.paragraph_index >= len(section.paragraphs):
                raise ValueError('读图步骤必须引用本节已有图表和段落。')
            count=item_count(section.visuals[step.visual_index])
            if len(set(step.item_indices)) != len(step.item_indices) or any(i<0 or i>=count for i in step.item_indices):
                raise ValueError('读图聚焦必须引用已有数据项，不能指向不存在的对象。')
        text=' '.join([guide.question]+[s.title+' '+s.explanation for s in guide.steps])
        if set(narrative_number_tokens(text))-allowed:
            raise ValueError('读图说明增加了材料外数值。')
