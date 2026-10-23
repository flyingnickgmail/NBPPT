"""Task-local execution context; the gateway never starts a model process."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import shutil

_worker = ContextVar('report_worker', default=None)


@contextmanager
def worker_runtime(folder: Path, binary: str):
    token = _worker.set((folder.resolve(), binary))
    try:
        yield
    finally:
        _worker.reset(token)


def binary():
    current = _worker.get()
    return current[1] if current else shutil.which('codex')


def temp_root():
    current = _worker.get()
    return str(current[0]) if current else None


def command(cmd, folder, references=()):
    current = _worker.get()
    isolated = os.getenv('NBPPT_REQUIRE_ISOLATION', 'false').lower() == 'true'
    if isolated and not current:
        raise RuntimeError('Report model calls must run on the isolated worker')
    if current and not Path(folder).resolve().is_relative_to(current[0]):
        raise ValueError('Report runtime escaped its job')
    env = {k: v for k, v in os.environ.items() if k in {
        'PATH', 'HOME', 'CODEX_HOME', 'TMPDIR', 'LANG', 'SSL_CERT_FILE',
        'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY'}}
    sandbox = None
    if isolated:
        from worker.isolation import isolated_command
        cmd, sandbox = isolated_command(cmd, folder, references)
    image_home = sandbox / '.codex' if sandbox else Path(os.getenv('CODEX_HOME', str(Path.home() / '.codex')))
    return cmd, env, image_home
