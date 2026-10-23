"""Conservative, local qualifier checks; no fabricated ranges or conversions."""
import re

SYMBOLS = {'exact': '', 'approx': '≈', 'gt': '>', 'lt': '<', 'gte': '≥', 'lte': '≤'}


def qualification(point):
    # Restrict the qualifier to the number's own phrase, not another statistic
    # somewhere in a long evidence quote. Unknown idioms fall back to a table.
    text = re.sub(r'\s+', ' ', point.qualifier_quote).strip().lower()
    pattern = r'(?<![\d.])[+-]?\d[\d,]*(?:\.\d+)?'
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1 or float(matches[0][0].replace(',', '')) not in {point.value, abs(point.value)}:
        raise ValueError('限定值短引文必须仅包含当前数值，不接受多项数字混用或换算。')
    prefix = text[:matches[0].start()].strip()
    suffix = text[matches[0].end():]
    if re.search(r'(?:at least|no less than|不少于|至少|不低于|≥)\s*$', prefix):
        relation = 'gte'
    elif re.search(r'(?:at most|no more than|不超过|最多|不高于|≤)\s*$', prefix):
        relation = 'lte'
    elif re.search(r'(?:more than|greater than|over|above|超过|高于|大于|逾|>)\s*$', prefix):
        relation = 'gt'
    elif re.search(r'(?:less than|below|under|低于|少于|小于|不足|<)\s*$', prefix):
        relation = 'lt'
    elif re.search(r'(?:around|about|roughly|approximately|nearly|almost|约|接近|近|≈|~)\s*$', prefix):
        relation = 'approx'
    else:
        # Do not silently strip an unrecognised qualifier.
        if re.search(r'more|less|over|under|around|about|rough|approxim|nearly|almost|超过|低于|约|近|至少|最多|[<>≥≤≈~]', prefix):
            raise ValueError('限定词未能可靠识别；保留原值表，不降为精确点。')
        relation = 'exact'
    raw = float(matches[0][0].replace(',', ''))
    if point.value < 0 and raw > 0:
        decline = re.search(r'down|declin|decreas|fell|fall|drop|下降|降低|减少', prefix) or re.search(r'lower|declin|decreas|drop|fall|down|下降|减少', suffix)
        if not decline and point.qualifier_quote in point.quote:
            # The short qualifier may be "almost 20%" while the same source
            # clause continues "drop in sales". Inspect only its adjacent clause.
            at = point.quote.index(point.qualifier_quote)
            before = re.split(r'[.;,，；。\d]', point.quote[max(0, at-60):at])[-1]
            after = re.split(r'[.;,，；。\d]', point.quote[at+len(point.qualifier_quote):at+len(point.qualifier_quote)+60])[0]
            decline = re.search(r'down|declin|decreas|fell|fall|drop|下降|降低|减少', before, re.I) or re.match(r'\s*(?:%|percent)?\s*(?:drop|decline|decrease|lower|fall|下降|减少)\b', after, re.I)
        if not decline:
            raise ValueError('负值必须有本句下降含义，不能从正增长改符号。')
        relation = {'gt': 'lt', 'lt': 'gt', 'gte': 'lte', 'lte': 'gte'}.get(relation, relation)
    return relation


def validate_qualified(visual, path, check, refs):
    if len({p.label for p in visual.points}) != len(visual.points):
        raise ValueError('限定值图对象不能重复。')
    for i, p in enumerate(visual.points):
        check(format(p.value, '.15g'), p.quote, path=f'{path}/points/{i}')
        refs(p.source_ids)
        if p.qualifier_quote not in p.quote:
            raise ValueError('限定值短引文须连续出自该点的原句。')
        # Selecting just "120%" must not hide the immediately preceding "over".
        number = re.search(r'[+-]?\d[\d,]*(?:\.\d+)?', p.qualifier_quote)
        if number:
            offset = p.quote.index(p.qualifier_quote) + number.start()
            preceding = re.sub(r'\s+', ' ', p.quote[max(0, offset-48):offset]).lower()
            marker = re.search(r'(at least|no less than|at most|no more than|more than|greater than|less than|over|above|below|under|around|about|roughly|approximately|nearly|almost|不少于|不低于|不超过|不高于|至少|最多|超过|高于|大于|低于|少于|小于|不足|接近|逾|约|近|[<>≥≤≈~])\s*$', preceding)
            if marker and marker[0].strip() not in re.sub(r'\s+', ' ', p.qualifier_quote).lower():
                raise ValueError('短引文遗漏了紧邻数值的限定词。')
        if qualification(p) != p.relation:
            raise ValueError(f'限定值图的符号与原句不符：{p.label}。')
