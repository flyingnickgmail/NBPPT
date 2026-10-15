"""Linux job isolation. Expose system runtime, selected skills and THIS job only."""
import os
from pathlib import Path
import shutil
import sys


def isolated_command(command, job_dir, references):
    if os.getenv('NBPPT_REQUIRE_ISOLATION', 'false').lower() != 'true':
        return command, None
    if sys.platform != 'linux' or os.geteuid() == 0 or not shutil.which('bwrap'):
        raise RuntimeError('Production execution requires a non-root Linux user and bubblewrap')
    job_dir = Path(job_dir).resolve()
    home = Path.home()
    auth = home / '.codex/auth.json'
    if not auth.is_file() or auth.is_symlink():
        raise RuntimeError('Dedicated Codex login required')
    sandbox_home = job_dir / '.agent-home'
    (sandbox_home / '.codex').mkdir(parents=True, exist_ok=True, mode=0o700)
    # The CLI needs its own login, but receives no gateway credentials or other jobs.
    args = ['bwrap', '--die-with-parent', '--new-session', '--unshare-pid',
            '--unshare-ipc', '--unshare-uts', '--unshare-user', '--cap-drop', 'ALL',
            '--clearenv', '--setenv', 'PATH', '/usr/local/bin:/usr/bin:/bin',
            '--setenv', 'HOME', str(sandbox_home), '--setenv', 'LANG', 'C.UTF-8',
            '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
            '--symlink', 'usr/sbin', '/sbin', '--symlink', 'usr/lib', '/lib',
            '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
    if Path('/usr/lib64').exists():
        args += ['--symlink', 'usr/lib64', '/lib64']
    for path in ['/etc/ssl', '/etc/fonts', '/etc/resolv.conf', '/etc/hosts', '/etc/nsswitch.conf', '/etc/localtime']:
        if Path(path).exists():
            args += ['--ro-bind', path, path]
    args += ['--bind', str(job_dir), str(job_dir),
             '--bind', str(auth), str(sandbox_home / '.codex/auth.json')]
    # Empty isolated config avoids recursive MCP connections and user hooks.
    (sandbox_home / '.codex/config.toml').write_text('model = "gpt-6-astra"\n')
    for ref in references:
        ref = Path(ref).resolve()
        if ref.is_file():
            args += ['--ro-bind', str(ref), str(ref)]
    # Absolute binary target must be part of the read-only /usr runtime.
    if not Path(command[0]).resolve().is_relative_to('/usr'):
        raise RuntimeError('Isolated Codex binary must be installed below /usr')
    args += ['--chdir', str(job_dir), '--', *command]
    return args, sandbox_home
