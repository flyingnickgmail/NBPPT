"""Operator-only import of actual rule/review records, never an approval author.

The store and authority.json must be owned/protected by the administrator.
No API or planner can call this importer or grant reviewer roles.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gateway.exec_pitch_contract import digest, canonical, hash_id
from gateway.exec_pitch_inputs import safe_file
from gateway.exec_pitch_review import write_once, validate_profile, dates, SCOPES


def import_record(root, kind, record, proof=None):
    owner = record.get('owner')
    if not hash_id(owner):
        raise ValueError('登记账户无效')
    if kind == 'profiles':
        validate_profile(record, owner, record['source_sha256'])
        if record['previous_sha256'] is not None:
            from gateway.exec_pitch_review import read_record
            parent = read_record(root, owner, kind, record['previous_sha256'])
            if parent['version'] + 1 != record['version'] or parent['client_id'] != record['client_id'] or parent['source_sha256'] != record['source_sha256']:
                raise ValueError('客户规则父版本不连续或跨范围')
    elif kind == 'receipts':
        required = {'owner','input_id','source_sha256','profile_sha256','video_sha256','samples_sha256',
                    'record_type','reviewer','evidence_sha256','created_at','expires_at','scopes'}
        if (set(record) != required or record['record_type'] not in ('human_record','test_fixture')
                or not all(hash_id(record[k]) for k in ('input_id','source_sha256','profile_sha256','video_sha256','samples_sha256'))
                or not isinstance(record['scopes'],dict) or set(record['scopes']) != set(SCOPES)
                or any(s not in ('PASSED','FAILED','NEEDS_REVIEW','UNAVAILABLE') for s in record['scopes'].values())):
            raise ValueError('最终画面回执格式无效')
        dates(record)
    else:
        raise ValueError('只能登记规则或最终画面审核')
    if record['record_type'] != 'candidate':
        authority = json.loads(safe_file(root, 'authority.json', 65536).read_text())
        role = 'rule_reviewers' if kind == 'profiles' else 'final_visual_reviewers'
        if record['reviewer'] not in authority.get(owner, {}).get(role, []):
            raise ValueError('审核人没有管理员授予的对应权限')
        if proof is None or proof.is_symlink() or not 0 < proof.stat().st_size <= 8*1024*1024:
            raise ValueError('必须提供真实审核依据文件')
        data = proof.read_bytes()
        if digest(data) != record['evidence_sha256']:
            raise ValueError('审核依据与记录摘要不一致')
        folder = root / owner / 'proofs'
        for p in (root, root / owner, folder):
            if p.is_symlink():raise ValueError('审核依据目录不安全')
            p.mkdir(exist_ok=True)
        destination = folder / record['evidence_sha256']
        if destination.exists():
            if safe_file(root,str(destination.relative_to(root)),8*1024*1024).read_bytes()!=data:
                raise ValueError('审核依据改变')
        else:
            with destination.open('xb') as stream:stream.write(data)
    key = write_once(root, owner, kind, record)
    if kind == 'receipts':
        folder = root / owner / 'final'
        if folder.is_symlink():raise ValueError('最终审核索引不安全')
        folder.mkdir(exist_ok=True)
        # Fail closed on competing decisions; a new film/rule version needs a
        # new receipt. No silent overwrite or self-revocation endpoint.
        pointer=folder / f"{record['video_sha256']}.json"
        data=canonical({'receipt_sha256':key})
        if pointer.exists() or pointer.is_symlink():
            if safe_file(root,str(pointer.relative_to(root)),1024).read_bytes()!=data:
                raise ValueError('同一成片已登记不同审核决定，不能覆盖')
        else:
            with pointer.open('xb') as stream:stream.write(data)
    return key


def main():
    p=argparse.ArgumentParser();p.add_argument('--store',required=True);p.add_argument('--kind',choices=('profiles','receipts'),required=True)
    p.add_argument('--record',required=True);p.add_argument('--proof');args=p.parse_args()
    root=Path(args.store)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():raise ValueError('管理员必须预先配置审核目录和权限')
    key=import_record(root,args.kind,json.loads(Path(args.record).read_text()),Path(args.proof) if args.proof else None)
    print(json.dumps({'sha256':key,'kind':args.kind,'approval_created_by_tool':False}))


if __name__=='__main__':main()
