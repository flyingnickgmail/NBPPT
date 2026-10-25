"""One local/CI gate. Failing phases, unknown skips or changing source fail closed."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OPTIONAL_SKIPS = {
    'test_video_generation': 'trusted MeloTTS runtime not configured',
    'test_video_speech': 'trusted MeloTTS runtime not configured',
    'test_video_options': 'optional Kokoro model not configured',
    'test_video_integrated': 'optional voice integration runtime required',
    'test_html_motion': 'optional pinned HTML runtime not configured',
    'test_product_visuals': 'optional pinned HTML runtime not configured',
    'test_deployed_reports': 'enable --deployment to run the real proxy acceptance',
}


def check_tracked_runtime(paths):
    for name in paths:
        if {'node_modules','.venv','venv'}.intersection(Path(name).parts):
            raise ValueError('Runtime dependencies must not be tracked, including local symlinks: '+name)


def source_inventory():
    names = subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'], cwd=ROOT).decode().split('\0')
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            for name in sorted(set(names)) if name and (ROOT/name).is_file() and not (ROOT/name).is_symlink()}


def check_results(xml_path):
    cases = ET.parse(xml_path).getroot().findall('.//testcase')
    skipped=[]
    for case in cases:
        if case.find('failure') is not None or case.find('error') is not None:
            raise ValueError('Backend test failures cannot pass the gate')
        skip = case.find('skipped')
        if skip is not None:
            module=case.get('classname','').split('.')[-1]
            reason=skip.get('message','')
            if module not in OPTIONAL_SKIPS or not reason.startswith(OPTIONAL_SKIPS[module]):
                raise ValueError('Unexpected skipped test: '+case.get('name','')+' / '+reason)
            skipped.append({'test':case.get('classname','')+'.'+case.get('name',''),'reason':reason})
    required=[c for c in cases if 'test_video_integrated' in c.get('classname','')
              and c.get('name','').endswith('[False]')]
    if len(required)!=1 or required[0].find('skipped') is not None:
        raise ValueError('Real silent media/refund/retry integration must execute, independent of optional voices')
    return {'passed':len(cases)-len(skipped),'skipped':skipped}


def html_test_runtime(env):
    """Pin test-only Chromium/font bytes; never configure the production process."""
    module=ROOT/'tests/browser/node_modules/playwright'
    if not (module/'package.json').is_file():
        raise RuntimeError('Install locked browser test dependencies with npm ci --prefix tests/browser')
    executable=Path(subprocess.check_output(['node','-e',
        'console.log(require(process.argv[1]).chromium.executablePath())',str(module)],
        cwd=ROOT,env=env,text=True).strip())
    if not executable.is_file(): raise RuntimeError('Install the locked acceptance Chromium before running the gate')
    version=subprocess.check_output([str(executable),'--version'],env=env,text=True)
    match=re.search(r'\d+\.\d+\.\d+\.\d+',version)
    if not match: raise RuntimeError('Cannot establish exact Chromium version')
    candidates=[Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf'),
                Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    font=next((p for p in candidates if p.is_file()),None)
    if font is None: raise RuntimeError('Install a CJK test font; do not silently skip rendering tests')
    return {'NBPPT_HTML_NODE':shutil.which('node'),'NBPPT_PLAYWRIGHT_MODULE':str(module),
            'NBPPT_CHROMIUM_BIN':str(executable),'NBPPT_CHROMIUM_VERSION':match.group(),
            'NBPPT_CHROMIUM_SHA256':hashlib.sha256(executable.read_bytes()).hexdigest(),
            'NBPPT_HTML_FONT':str(font),'NBPPT_HTML_FONT_SHA256':hashlib.sha256(font.read_bytes()).hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='Absolute task evidence parent; each run uses a fresh subdirectory')
    parser.add_argument('--deployment',action='store_true',help='Require real TCP/TLS/nginx proxy acceptance')
    args=parser.parse_args()
    if not args.output.is_absolute(): parser.error('--output must be absolute')
    run=args.output.resolve()/('run-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    run.mkdir(parents=True)
    (run/'tmp').mkdir()
    before=source_inventory()
    tree_hash=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()
    report={'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'tree_sha256':tree_hash,'source_files':before,'phases':{},'deployment_acceptance':args.deployment,'result':'FAILED'}
    env={**os.environ,'TMPDIR':str(run/'tmp'),'TMP':str(run/'tmp'),'TEMP':str(run/'tmp'),
         'DATABASE_PATH':str(run/'imports.db'),'NBPPT_JOBS_ROOT':str(run/'import-jobs'),
         'PYTHONDONTWRITEBYTECODE':'1','NBPPT_TEST_PYTHON':sys.executable,'NBPPT_ACCEPTANCE_TREE_SHA':tree_hash}
    def phase(name, command):
        with (run/(name+'.log')).open('w') as log:
            result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        report['phases'][name]={'exit_code':result.returncode,'log':name+'.log'}
        if result.returncode: raise RuntimeError(f'{name} failed; see {run/(name+".log")}')
        print(name+': PASSED',flush=True)
    try:
        check_tracked_runtime(subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0'))
        for tool in ('node','ffmpeg','ffprobe'):
            if not shutil.which(tool): raise RuntimeError('Mandatory acceptance dependency missing: '+tool)
        if args.deployment and any(not shutil.which(p) for p in ('nginx','openssl')):
            raise RuntimeError('Deployment acceptance requires nginx and openssl; do not skip the proxy checks')
        env.update(html_test_runtime(env))
        report['html_runtime']={key:value for key,value in env.items() if key in (
            'NBPPT_CHROMIUM_VERSION','NBPPT_CHROMIUM_SHA256','NBPPT_HTML_FONT_SHA256')}
        for name in before:
            if name.endswith('.py') and (name.startswith(('gateway/','tests/','tools/')) or name.startswith('worker/') and name.count('/')==1):
                ast.parse((ROOT/name).read_text(),filename=name)
        phase('syntax_and_diff',['git','diff','--check'])
        phase('browser_test_syntax',['node','--check','tools/workbench_acceptance.mjs'])
        phase('dependencies',[sys.executable,'-m','pip','check'])
        phase('video_docs',[sys.executable,'-B','tools/check_video_docs.py'])
        # Catch real browser/host incompatibilities before long media regressions.
        # The final result still requires every phase and the same source tree.
        phase('workbench',['node','tools/workbench_acceptance.mjs',str(run/'workbench')])
        receipt=json.loads((run/'workbench/receipt.json').read_text())
        if receipt.get('result')!='PASSED' or receipt.get('page_path')!='/' or receipt.get('tree_sha256')!=tree_hash:
            raise ValueError('Browser evidence must refer to the tested root product and source tree')
        phase('backend',[sys.executable,'-B','-m','pytest','-q','-ra','--basetemp',str(run/'pytest'),
                         '-o','cache_dir='+str(run/'pytest-cache'),'--junitxml='+str(run/'pytest.xml')]+(['--deployment'] if args.deployment else []))
        report['backend']=check_results(run/'pytest.xml')
        if args.deployment and any('test_deployed_reports' in s['test'] for s in report['backend']['skipped']):
            raise ValueError('Explicit deployment acceptance must not be skipped')
        frontends=sorted((ROOT/'tests').glob('*.cjs'))+sorted((ROOT/'tools/report_studio/tests').glob('*.cjs'))
        phase('frontend',['node','--test',*[str(p.relative_to(ROOT)) for p in frontends]])
        if source_inventory()!=before: raise ValueError('Source changed during checks; evidence is stale, rerun after edits stop')
        report['result']='PASSED'
    except Exception as exc:
        report['error']=str(exc)
        print(str(exc),file=sys.stderr)
    finally:
        (run/'gate.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print('Evidence: '+str(run),flush=True)
    return 0 if report['result']=='PASSED' else 1


if __name__=='__main__':
    raise SystemExit(main())
