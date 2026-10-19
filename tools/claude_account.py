#!/usr/bin/env python3
"""Operator-only account status/reset and non-copying credential retirement.

Run from the repository: python -m tools.claude_account status
No command logs in, copies credentials, changes a subscription or recharges.
"""
import argparse
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

from worker.claude_account import AccountGate, ClaudeProfile, verify_login, ProviderUnavailable


def duplicate_profiles(canonical, legacy_homes):
    source = canonical.credentials
    if not source.is_file() or source.is_symlink():
        return []
    digest = hashlib.sha256(source.read_bytes()).digest()
    duplicates = []
    for value in legacy_homes:
        path = Path(value).expanduser() / '.claude/.credentials.json'
        if path.absolute() == source.absolute():
            continue
        if path.is_symlink():
            raise ValueError('拒绝处理符号链接凭据')
        if path.is_file():
            config = path.parent.parent / '.claude.json'
            same_account = False
            if config.is_file() and not config.is_symlink():
                account = json.loads(config.read_text()).get('oauthAccount', {}).get('accountUuid')
                same_account = isinstance(account, str) and 'claude-' + hashlib.sha256(account.encode()).hexdigest()[:24] == canonical.account_id
            if same_account or hashlib.sha256(path.read_bytes()).digest() == digest:
                duplicates.append(path)
    return duplicates


def retire_duplicates(profile, homes, gate):
    # Explicit maintenance is allowed even while a circuit is blocked.
    fd = gate._open_lock()
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Claude 正在使用凭据，不能进行迁移')
        duplicates = duplicate_profiles(profile, homes)
        retired = []
        for source in duplicates:
            target = source.with_name(source.name + '.retired-' + str(time.time_ns()))
            source.rename(target)  # Move, never copy; the official CLI no longer discovers it.
            target.chmod(0o600)
            retired.append(str(target))
        return retired
    finally:
        os.close(fd)


async def execute_prompt(profile, gate, binary, prompt):
    # Managed diagnostic callers share the very same account lease as product jobs.
    if os.geteuid() != profile.home.stat().st_uid:
        raise ValueError('诊断执行必须以唯一登录所属用户运行，避免生成另一份所有权不符的凭据')
    await verify_login(binary, profile)
    async with gate.lease():
        env = {k:v for k,v in os.environ.items() if k in ('PATH','LANG','TMPDIR')}
        env.update(HOME=str(profile.home), CLAUDE_CODE_MAX_RETRIES='2')
        proc = await asyncio.create_subprocess_exec(binary, '--safe-mode', '--restricted',
            '--setting-sources', '', '--no-session-persistence',
            '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--tools', '',
            '--model', os.getenv('NBPPT_CLAUDE_MODEL') or 'sonnet',
            '--max-budget-usd', '.10', '--max-turns', '1',
            '--output-format', 'stream-json', '--verbose', '--print', prompt,
            env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True, limit=2_000_000)
        from worker.claude_generation import stop_cli
        success = False
        try:
            async with asyncio.timeout(120):
                async for line in proc.stdout:
                    try: value=json.loads(line)
                    except ValueError: continue
                    if isinstance(value,dict):
                        gate.record_event(value)
                        if value.get('type')=='result':
                            success = value.get('subtype') == 'success' and value.get('is_error') is False
                            print(json.dumps({'type':'result','subtype':value.get('subtype'),'is_error':value.get('is_error')}))
                await proc.wait()
            return proc.returncode or (0 if success else 1)
        except ProviderUnavailable:
            await stop_cli(proc, force=True)
            raise
        finally:
            await stop_cli(proc)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['status','reset','audit','retire-duplicates','exec'])
    parser.add_argument('--legacy-home',action='append',default=[])
    parser.add_argument('--prompt-file',type=Path)
    args=parser.parse_args()
    profile=ClaudeProfile.configured();gate=AccountGate.configured(profile)
    if args.action=='status': print(json.dumps(gate.status(),ensure_ascii=False))
    elif args.action=='reset':
        asyncio.run(gate.reset()); print('已恢复受控入口；未发起生成或重试，请先确认账号问题已处理')
    elif args.action=='audit':
        print(json.dumps({'duplicate_active_paths':[str(p) for p in duplicate_profiles(profile,args.legacy_home)]},ensure_ascii=False))
    elif args.action=='retire-duplicates':
        print(json.dumps({'retired_paths':retire_duplicates(profile,args.legacy_home,gate)},ensure_ascii=False))
    else:
        if not args.prompt_file: parser.error('exec requires --prompt-file')
        import shutil
        binary=os.getenv('CLAUDE_BIN') or shutil.which('claude')
        if not binary: raise ValueError('Claude CLI 不存在')
        raise SystemExit(asyncio.run(execute_prompt(profile,gate,binary,args.prompt_file.read_text())))


if __name__=='__main__': main()
