"""Resolve cover references from existing facts, preserving labels, units and citations."""
import re
def evidence_catalog(report):
    result = {}

    def put(ref, value, label, quote, ids, context, section=-1, basis=''):
        if quote:
            result[ref] = dict(value=str(value), label=label, quote=quote,
                               source_ids=ids, context=context, section=section, basis=basis)

    for i, m in enumerate(report.metrics):
        put(f'metrics/{i}', m.value, m.label, m.quote, m.source_ids, report.subtitle)
    for si, section in enumerate(report.sections):
        for vi, v in enumerate(section.visuals):
            base = f'sections/{si}/visuals/{vi}'
            context = v.title + (' · ' + v.note if v.note else '')
            if v.kind == 'matrix':
                for ri, row in enumerate(v.rows):
                    for ci, cell in enumerate(row.cells):
                        col = v.columns[ci]
                        value = cell.value
                        if col.unit and re.fullmatch(r'[+-]?\d[\d,. ]*', value) and not re.search(r'[：:；;/]', col.unit):
                            value += ' ' + col.unit
                        put(f'{base}/rows/{ri}/cells/{ci}', value,
                            row.label + ' · ' + col.label, cell.quote,
                            cell.source_ids or v.source_ids, context, si, v.note)
            elif v.kind == 'contrast':
                for ri, row in enumerate(v.rows):
                    for side in ('left', 'right'):
                        item = getattr(row, side)
                        put(f'{base}/rows/{ri}/{side}', item.detail, row.label + ' · ' + item.label,
                            item.quote, item.source_ids or v.source_ids, context, si, item.nature)
            elif v.kind == 'evidence_strip':
                for ii, item in enumerate(v.items):
                    put(f'{base}/items/{ii}', item.detail, item.label, item.quote,
                        item.source_ids or v.source_ids, context, si, item.nature)
            elif v.kind == 'qualified_dot':
                from .qualified import SYMBOLS
                for pi, p in enumerate(v.points):
                    put(f'{base}/points/{pi}', f'{SYMBOLS[p.relation]}{p.value:g}{v.unit}', p.label,
                        p.quote, p.source_ids or v.source_ids, context, si, v.basis)
            elif v.kind in ('bar', 'line'):
                for pi, p in enumerate(v.points):
                    put(f'{base}/points/{pi}', f'{p.value}{v.unit}', p.label,
                        p.quote, p.source_ids or v.source_ids, context, si, v.note)
            elif v.kind == 'waterfall':
                for key,p in [('start',v.start), *[(f'changes/{j}',p) for j,p in enumerate(v.changes)], ('end',v.end)]:
                    put(f'{base}/{key}', f'{p.value}{v.unit}', p.label,
                        p.quote, p.source_ids or v.source_ids, context, si, v.basis)
            elif v.kind == 'comparison':
                for ri,row in enumerate(v.rows):
                    for side,period in [('before',v.before_label),('after',v.after_label)]:
                        p=getattr(row,side)
                        put(f'{base}/rows/{ri}/{side}', f'{p.value}{v.unit}',row.label+' · '+period,
                            p.quote,p.source_ids or v.source_ids,context,si,v.note)
            elif v.kind == 'multiseries':
                for sj, series in enumerate(v.series):
                    for pi, p in enumerate(series.points):
                        if p:
                            put(f'{base}/series/{sj}/points/{pi}', f'{p.value}{v.unit}',
                                v.categories[pi] + ' · ' + series.label, p.quote,
                                p.source_ids or v.source_ids, context + ' · ' + v.basis, si, v.basis)
    return result


def validate_editorial(report):
    cover = report.editorial
    if not cover:
        return
    catalog = evidence_catalog(report)
    refs = [item.ref for item in cover.items]
    if len(set(refs)) != len(refs) or any(ref not in catalog for ref in refs):
        raise ValueError('封面必须引用不同的、已有引文的报告事实。')
    if cover.layout in ('sequence', 'constellation') and len(refs) < 3:
        raise ValueError('流程或多维封面至少需要三项证据。')
    from .evidence import number_tokens
    available = set(number_tokens(report.title + ' ' + ' '.join(
        fact['quote'] + ' ' + fact['label'] + ' ' + fact['context'] for fact in catalog.values())))
    text = ' '.join([cover.question, cover.takeaway, cover.boundary] + [item.caption for item in cover.items])
    if any(number not in available for number in number_tokens(text)):
        raise ValueError('封面说明不得增加现有证据未提供的数字。')
