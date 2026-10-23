"""Categorical diagrams without invented scores, durations or causal links."""


def validate_qualitative(visual, path, check, refs):
    if visual.kind == 'contrast':
        if visual.left_label == visual.right_label:
            raise ValueError('定性对照必须比较两个不同对象。')
        for i, row in enumerate(visual.rows):
            for side in ('left', 'right'):
                item = getattr(row, side)
                check(item.label + ' ' + item.detail, item.quote,
                      path=f'{path}/rows/{i}/{side}', field='detail')
                refs(item.source_ids)
    elif visual.kind == 'membership':
        if len(set(visual.sets)) != len(visual.sets):
            raise ValueError('归属点阵的集合名不能重复。')
        for i, item in enumerate(visual.items):
            seen = set()
            for j, relation in enumerate(item.relations):
                if relation.set_index >= len(visual.sets) or relation.set_index in seen:
                    raise ValueError('归属点阵引用了不存在或重复的集合。')
                seen.add(relation.set_index)
                check(item.label + ' ' + item.detail, relation.quote,
                      path=f'{path}/items/{i}/relations/{j}', field='quote')
                refs(relation.source_ids)
    elif visual.kind == 'evidence_strip':
        if len({item.nature for item in visual.items}) < 2:
            raise ValueError('证据分层至少需要两种证据性质，单一类别用正文。')
        for i, item in enumerate(visual.items):
            check(item.label + ' ' + item.detail, item.quote,
                  path=f'{path}/items/{i}', field='detail')
            refs(item.source_ids)
