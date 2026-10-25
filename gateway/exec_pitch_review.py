"""Operator-owned, content-addressed rules and final-film review receipts.

The configured store is an administrator trust boundary, never an upload path.
Candidate profiles are useful review inputs, never customer authorization.
"""
import ipaddress
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from gateway.exec_pitch_contract import canonical, digest, hash_id
from gateway.exec_pitch_inputs import safe_file
from gateway.video_contract import _plain_text

SCOPES = ('brand', 'watermark', 'forbidden_terms', 'disclosure', 'redaction')


def store():
    raw = os.getenv('NBPPT_EXEC_REVIEW_ROOT', '')
    root = Path(raw)
    if not raw or not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError('未配置管理员审核记录目录')
    return root


def read_record(root, owner, kind, key, maximum=65536):
    if not hash_id(owner) or not hash_id(key) or kind not in ('profiles', 'receipts'):
        raise ValueError('审核记录编号非法')
    path = safe_file(root, f'{owner}/{kind}/{key}.json', maximum)
    record = json.loads(path.read_text())
    if digest(canonical(record)) != key:
        raise ValueError('审核记录摘要改变')
    return record


def dates(record):
    values = [datetime.fromisoformat(record[k]) for k in ('created_at', 'expires_at')]
    if any(d.tzinfo is None for d in values) or not values[0] <= datetime.now(timezone.utc) < values[1]:
        raise ValueError('审核记录时间无效或过期')


def validate_profile(p, owner, source_sha):
    fields = {'version', 'previous_sha256', 'owner', 'source_sha256', 'client_id', 'record_type',
              'created_at', 'expires_at', 'reviewer', 'evidence_sha256', 'brand', 'forbidden_terms',
              'required_terms', 'disclosure', 'redact_ip', 'require_product_assets', 'number_policy'}
    if (not isinstance(p, dict) or set(p) != fields or type(p['version']) is not int or not 1 <= p['version'] <= 10000
            or (p['version'] == 1) != (p['previous_sha256'] is None)
            or p['previous_sha256'] is not None and not hash_id(p['previous_sha256'])
            or p['owner'] != owner or p['source_sha256'] != source_sha
            or p['record_type'] not in ('candidate', 'human_record', 'test_fixture')
            or p['disclosure'] not in ('external', 'internal') or p['number_policy'] != 'literal_source_only'
            or type(p['redact_ip']) is not bool or type(p['require_product_assets']) is not bool):
        raise ValueError('客户规则版本、账户、原文或有限策略无效')
    for k in ('client_id', 'reviewer', 'brand'):
        _plain_text(p[k], k, 80)
    if p['record_type'] == 'human_record' and not hash_id(p['evidence_sha256']):
        raise ValueError('客户规则缺少真实授权证据摘要')
    if p['evidence_sha256'] is not None and not hash_id(p['evidence_sha256']):
        raise ValueError('客户规则授权证据编号非法')
    for k in ('forbidden_terms', 'required_terms'):
        if not isinstance(p[k], list) or len(p[k]) > 40:
            raise ValueError('客户用语数量超限')
        for term in p[k]:
            _plain_text(term, k, 80)
    dates(p)
    return p


def load_profile(value, spec):
    g = value['governance']; owner = spec['video_input_owner']; root = store()
    p = validate_profile(read_record(root, owner, 'profiles', g['profile_sha256']), owner, value['source_sha256'])
    if p['record_type'] == 'test_fixture' and value['media_kind'] != 'synthetic_fixture':
        raise ValueError('测试规则不能作为真实客户授权')
    if p['record_type'] == 'human_record':
        authority = json.loads(safe_file(root, 'authority.json', 65536).read_text())
        if p['reviewer'] not in authority.get(owner, {}).get('rule_reviewers', []):
            raise ValueError('客户规则审核人未获管理员授权')
        proof = safe_file(root, f"{owner}/proofs/{p['evidence_sha256']}", 8*1024*1024)
        if digest(proof.read_bytes()) != p['evidence_sha256']:
            raise ValueError('客户规则批准证据改变')
    # Verify the complete bounded ancestry, including client/source isolation.
    current = p
    for _ in range(100):
        if current['previous_sha256'] is None:
            return p
        parent = validate_profile(read_record(root, owner, 'profiles', current['previous_sha256']), owner, value['source_sha256'])
        if parent['version'] + 1 != current['version'] or parent['client_id'] != p['client_id']:
            raise ValueError('客户规则版本链不连续或跨客户')
        current = parent
    raise ValueError('客户规则版本链超过100版上限')


def declared_text(value):
    """Only on-screen/spoken fields; never scan rule/source metadata as output."""
    parts = [value['title']]
    for s in value['shots']:
        parts.append(s['narration'])
        m = s.get('motion', {})
        parts.extend([m.get('headline', ''), *m.get('labels', [])])
    if 'story' in value:
        b=value['story']
        parts.extend([b['question'],b['entity'],b['proof']['limitation'],b['ending']['next_step']])
        parts.extend(a['title'] for a in b['acts'])
    return '\n'.join(parts)


def verdict(value, spec, video=None, frames=None):
    p = load_profile(value, spec); text = declared_text(value)
    violations = [t for t in p['forbidden_terms'] if t in text]
    missing = [t for t in p['required_terms'] if t not in text]
    ips = []
    if p['redact_ip']:
        for token in re.findall(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', text):
            try:
                ipaddress.ip_address(token); ips.append(token)
            except ValueError:
                pass
    base = {'profile_sha256': value['governance']['profile_sha256'], 'profile_version': p['version'],
            'rule_record_type': p['record_type'], 'forbidden_found': violations, 'required_missing': missing,
            'unredacted_ips': ips, 'text_scope': 'declared_visible_and_spoken_text_not_ocr',
            'content_status': 'NOT_REVIEWED'}
    if violations or missing or ips:
        return {**base, 'status': 'FAILED', 'reason': '登记画面或口播违反客户文字规则'}
    if p['record_type'] == 'candidate':
        return {**base, 'status': 'UNAVAILABLE', 'reason': '规则为待审候选，未取得客户规则/品牌授权；不升级为通过'}
    if p['require_product_assets'] and not value.get('product_visuals'):
        return {**base, 'status': 'UNAVAILABLE', 'reason': '规则要求已审客户产品素材，当前缺失'}
    if video is None or frames is None:
        return {**base, 'status': 'NEEDS_REVIEW', 'reason': '等待绑定最终成片及取样帧的真实审核'}
    video_sha = digest(video.read_bytes()); owner = spec['video_input_owner']; root = store()
    pointer = root / owner / 'final' / f'{video_sha}.json'
    if not pointer.exists():
        return {**base, 'status': 'NEEDS_REVIEW', 'reason': '缺少最终画面审核回执'}
    ref = json.loads(safe_file(root, f'{owner}/final/{video_sha}.json', 1024).read_text())
    if not isinstance(ref, dict) or set(ref) != {'receipt_sha256'}:
        raise ValueError('最终画面审核索引非法')
    a = read_record(root, owner, 'receipts', ref['receipt_sha256'])
    fields = {'owner', 'input_id', 'source_sha256', 'profile_sha256', 'video_sha256', 'samples_sha256',
              'record_type', 'reviewer', 'evidence_sha256', 'created_at', 'expires_at', 'scopes'}
    if (not isinstance(a, dict) or set(a) != fields or a['owner'] != owner or a['input_id'] != spec['video_input_id']
            or a['source_sha256'] != value['source_sha256'] or a['profile_sha256'] != base['profile_sha256']
            or a['video_sha256'] != video_sha or a['samples_sha256'] != digest(canonical(frames['samples']))
            or a['record_type'] != ('test_fixture' if value['media_kind'] == 'synthetic_fixture' else 'human_record')
            or not hash_id(a['evidence_sha256']) or set(a['scopes']) != set(SCOPES)
            or any(s not in ('PASSED', 'FAILED', 'NEEDS_REVIEW', 'UNAVAILABLE') for s in a['scopes'].values())):
        raise ValueError('最终画面审核未绑定账户、版本、原文、规则、成片及全部取样帧')
    dates(a); _plain_text(a['reviewer'], 'reviewer', 80)
    # Role grants belong to the operator store, never the receipt or model.
    authorities = json.loads(safe_file(root, 'authority.json', 65536).read_text())
    if a['reviewer'] not in authorities.get(owner, {}).get('final_visual_reviewers', []):
        raise ValueError('审核人无管理员授予的最终画面审核权限')
    proof = safe_file(root, f"{owner}/proofs/{a['evidence_sha256']}", 8*1024*1024)
    if digest(proof.read_bytes()) != a['evidence_sha256']:
        raise ValueError('最终画面审核依据改变')
    status = ('PASSED' if all(s == 'PASSED' for s in a['scopes'].values()) else
              'FAILED' if 'FAILED' in a['scopes'].values() else 'NEEDS_REVIEW')
    return {**base, 'status': status, 'receipt_sha256': ref['receipt_sha256'], 'scopes': a['scopes'],
            'reviewer': a['reviewer'], 'automatic_visual_ocr': 'UNAVAILABLE',
            'reason': '管理员登记的最终画面专项审核；不代替内容或译审批准'}


def validate_governance(value, spec):
    g = value.get('governance')
    if g is None:
        return
    if (not isinstance(g, dict) or set(g) != {'profile_sha256'} or not hash_id(g['profile_sha256'])
            or value.get('quality', {}).get('profile') != 'exec_pitch_p4'):
        raise ValueError('P5规则必须绑定明确P4检查与可信规则摘要')


def write_once(root, owner, kind, record):
    """Operator helper; no application endpoint exposes this write authority."""
    if not hash_id(owner) or kind not in ('profiles', 'receipts'):
        raise ValueError('审核登记范围无效')
    if root.is_symlink() or not root.is_absolute():
        raise ValueError('审核目录不安全')
    key = digest(canonical(record)); folder = root / owner / kind
    for p in (root, root / owner, folder):
        if p.is_symlink():
            raise ValueError('审核目录不能是符号链接')
        p.mkdir(exist_ok=True)
    target = folder / f'{key}.json'
    if target.exists():
        if safe_file(root, str(target.relative_to(root)), 65536).read_bytes() != canonical(record):
            raise ValueError('已登记审核记录发生变化')
    else:
        with target.open('xb') as stream:
            stream.write(canonical(record))
    return key
