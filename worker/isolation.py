"""Linux job isolation. Expose system runtime, selected skills and THIS job only."""
import os
import json
from pathlib import Path
import shutil
import sys


def isolated_command(command, job_dir, references, *, agent="codex", profile=None, runtime_paths=()):
    if agent not in ("codex", "claude", "renderer"):
        raise ValueError("Unknown isolated agent")
    if os.getenv('NBPPT_REQUIRE_ISOLATION', 'false').lower() != 'true':
        return command, None
    if sys.platform != 'linux' or os.geteuid() == 0 or not shutil.which('bwrap'):
        raise RuntimeError('Production execution requires a non-root Linux user and bubblewrap')
    job_dir = Path(job_dir).resolve()
    home = profile.home if profile is not None else Path.home()
    auth_relative = '.codex/auth.json' if agent == 'codex' else '.claude/.credentials.json'
    auth = home / auth_relative
    if agent != "renderer" and (not auth.is_file() or auth.is_symlink()):
        raise RuntimeError(f'Dedicated {agent.title()} login required')
    sandbox_home = job_dir / '.agent-home'
    (sandbox_home / Path(auth_relative).parent).mkdir(parents=True, exist_ok=True, mode=0o700)
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
    # Ubuntu's /usr/lib/libreoffice/share/registry points outside /usr.
    # Only the offline renderer needs this public, root-owned configuration.
    if agent == 'renderer' and Path('/etc/libreoffice').is_dir():
        args += ['--ro-bind', '/etc/libreoffice', '/etc/libreoffice']
    args += ['--bind', str(job_dir), str(job_dir)]
    if agent == 'claude':
        # A directory bind supports the official client's atomic token refresh.
        # There is one host credential store, not a credential copy per job.
        args += ['--bind', str(auth.parent), str(sandbox_home / '.claude')]
    elif agent == 'codex':
        args += ['--bind', str(auth), str(sandbox_home / auth_relative)]
    else:
        args += ['--unshare-net']
    # Empty isolated config avoids recursive MCP connections and user hooks.
    if agent == 'codex':
        (sandbox_home / '.codex/config.toml').write_text('model = "gpt-6-astra"\n')
    elif agent == 'claude':
        metadata = {'hasCompletedOnboarding': True}
        config = home / '.claude.json'
        if config.is_file() and not config.is_symlink():
            account = json.loads(config.read_text()).get('oauthAccount')
            if account:
                metadata['oauthAccount'] = account
        (sandbox_home / '.claude.json').write_text(json.dumps(metadata))
        args += ['--setenv', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC', '1']
        args += ['--setenv', 'CLAUDE_CODE_MAX_RETRIES', '2']
        args += ['--setenv', 'CLAUDE_CODE_SUBPROCESS_ENV_SCRUB', '1']
    for runtime in runtime_paths:
        runtime = Path(runtime).resolve(strict=True)
        if not runtime.is_relative_to('/usr'):
            args += ['--ro-bind', str(runtime), str(runtime)]
    for ref in references:
        ref = Path(ref).resolve()
        if ref.is_file():
            args += ['--ro-bind', str(ref), str(ref)]
    # Absolute binary target must be part of the read-only /usr runtime.
    if not Path(command[0]).resolve().is_relative_to('/usr'):
        raise RuntimeError('Isolated agent binary must be installed below /usr')
    args += ['--chdir', str(job_dir), '--', *command]
    return args, sandbox_home
