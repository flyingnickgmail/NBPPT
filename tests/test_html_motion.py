"""Data injection, real offline Chromium, deterministic seek and encoded cuts."""
import asyncio
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

import pytest

from gateway.motion_contract import validate_motion
from gateway.motion_delivery import verify_motion_chunks,selection_expression
from gateway.exec_pitch_contract import canonical,digest
from gateway.exec_pitch_inputs import load_input
from tools.exec_pitch_fixture import build_fixture
from worker.html_motion_renderer import ROOT,render_chunks
from worker.video_subtitles import _find_ffmpeg


@pytest.mark.parametrize('change',[
 {'script':'alert(1)'},{'css':'url(https://example.invalid)'},{'layout':'custom'},
 {'headline':'<img src=x onerror=alert(1)>'},{'labels':['太长的对象标签'*8,'核对']},
 {'focus':True},{'focus':-1},{'headline':'提升99%'},{'lottie':{'assets':[{'p':'http://example.invalid'}]}},
])
def test_untrusted_motion_is_data_only(change):
    data={'layout':'process','headline':'查证后再判断','labels':['来源','核对'],'focus':0}
    with pytest.raises(ValueError):validate_motion({**data,**change},'来源与核对')


def prepare(tmp_path,monkeypatch,layout='title',portrait=False):
    registry=tmp_path/'registry';source,input_id,value=build_fixture(registry,'motion-test',6)
    # Register only strict host grammar data; neither source text nor the input
    # can choose scripts, paths, fonts, browser flags or an animation JSON file.
    for shot in value['shots']:
        shot['motion']={'layout':layout,'headline':'先保留原文','labels':['原文','核对'],'focus':0}
    old=registry/digest(b'motion-test')/input_id
    input_id=digest(canonical(value));new=old.parent/input_id;old.rename(new);(new/'input.json').write_bytes(canonical(value))
    spec={'original_prompt_cn':source,'video_duration_sec':6,'video_aspect_ratio':'9:16' if portrait else '16:9',
          'video_width':720 if portrait else 1280,'video_height':1280 if portrait else 720}
    monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry))
    value,timeline,registry=load_input(digest(b'motion-test'),input_id,spec)
    job=tmp_path/'video_abcdef1234';(job/'staging/assets').mkdir(parents=True)
    return job,spec,value,timeline,registry


def require_runtime():
    if not os.environ.get('NBPPT_CHROMIUM_SHA256'):
        pytest.skip('optional pinned HTML runtime not configured; run with the documented runtime environment')


@pytest.mark.parametrize('portrait',[False,True])
def test_actual_html_lottie_chunks_seek_deterministically_and_keep_native_geometry(tmp_path,portrait,monkeypatch):
    require_runtime();job,spec,value,timeline,registry=prepare(tmp_path,monkeypatch,portrait=portrait)
    picture=render_chunks(job,spec,value,timeline,registry,str(_find_ffmpeg()))
    ledger=json.loads((job/'html-render/chunks.json').read_text());browser=json.loads((job/'html-render/browser.json').read_text())
    assert ledger['total_frames']==144 and ledger['network_requests']==[] and ledger['errors']==[]
    assert len(ledger['seek_determinism'])==2
    assert all(r['first_sha256']==r['reseek_sha256'] for r in ledger['seek_determinism'])
    assert not any(arg in ('--no-sandbox','--disable-setuid-sandbox') for arg in browser['arguments'])
    assert browser['profile']==str(job/'html-render/profile')
    if sys.platform=='linux':
        assert Path(browser['socket_temp']).parent==Path(os.environ['NBPPT_HTML_SOCKET_ROOT'])
        assert browser['profile'].startswith(str(job))
    assert all(str(job/'html-render') in a for a in browser['arguments'] if any(k in a for k in ('--user-data-dir=','--disk-cache-dir=','--crash-dumps-dir=')))
    # Exercise the independent final-boundary check using the concatenated file.
    import shutil
    shutil.copyfile(picture,job/'staging'/f'{job.name}_video.mp4')
    spec.update(exec_pitch_timeline=timeline)
    _,facts=verify_motion_chunks(spec,job/'staging')
    assert facts['boundary_frames']==4 and facts['max_mean_pixel_error']<8
    ledger['chunks'][1]['start_frame']-=1
    (job/'staging/render_chunks.json').write_text(json.dumps(ledger))
    with pytest.raises(ValueError,match='时间轴'):verify_motion_chunks(spec,job/'staging')


@pytest.mark.parametrize('unsafe',['missing','public','symlink'])
def test_linux_socket_root_is_operator_owned_and_never_implicitly_shared(tmp_path,unsafe):
    if sys.platform!='linux':return
    require_runtime()
    work=tmp_path/'socket-check';work.mkdir()
    config={'font':os.environ['NBPPT_HTML_FONT'],'font_sha256':os.environ['NBPPT_HTML_FONT_SHA256']}
    (work/'config.json').write_text(json.dumps(config))
    with tempfile.TemporaryDirectory(prefix='',dir=os.environ['NBPPT_HTML_SOCKET_ROOT']) as short:
        root=Path(short)
        if unsafe=='public':root.chmod(0o755)
        if unsafe=='symlink':
            link=root/'s';link.symlink_to(root,target_is_directory=True);root=link
        environment={**os.environ,'NBPPT_HTML_SOCKET_ROOT':'' if unsafe=='missing' else str(root)}
        result=subprocess.run([os.environ['NBPPT_HTML_NODE'],str(ROOT/'render.mjs'),str(work)],
                              env=environment,capture_output=True,text=True,timeout=15)
        assert result.returncode and 'Linux Chromium socket root' in result.stderr
        assert not (work/'browser.json').exists()


def test_real_browser_cancellation_closes_its_own_profile_processes(tmp_path,monkeypatch):
    require_runtime();job,spec,value,timeline,registry=prepare(tmp_path,monkeypatch)
    # Build the host config without launching via Python's blocking wrapper.
    work=job/'cancel-browser';work.mkdir();(work/'tmp').mkdir()
    config={'width':1280,'height':720,'total_frames':14400,'chunk_frames':96,
            'shots':[{'shot_num':1,'frames':14400,'brand':'取消回归','motion':value['shots'][0]['motion']}],
            'font':os.environ['NBPPT_HTML_FONT'],'font_sha256':os.environ['NBPPT_HTML_FONT_SHA256'],'ffmpeg':str(_find_ffmpeg())}
    (work/'config.json').write_text(json.dumps(config))
    environment={**os.environ,'TMPDIR':str(work/'tmp')}
    with (work/'cancel.log').open('wb') as log:
        proc=subprocess.Popen([os.environ['NBPPT_HTML_NODE'],str(ROOT/'render.mjs'),str(work)],env=environment,stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+15
            while not (work/'browser.json').exists() and proc.poll() is None and time.monotonic()<deadline:time.sleep(.05)
            assert (work/'browser.json').exists(),(work/'cancel.log').read_text()
            browser=json.loads((work/'browser.json').read_text());proc.terminate();proc.wait(timeout=10)
            # The receipt lists only this renderer's fresh browser process tree.
            for p in browser['pids']:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    try:os.kill(p['pid'],0)
                    except ProcessLookupError:break
                    time.sleep(.05)
                else:pytest.fail(f"owned Chromium child survived cancellation: {p['type']}")
        finally:
            if proc.poll() is None:proc.kill();proc.wait(timeout=5)


def test_long_boundary_selection_survives_actual_ffmpeg_parser():
    expression=selection_expression(list(range(144)))
    subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','color=s=64x64:r=24:d=6',
                    '-vf','select='+expression,'-f','null','-'],check=True,capture_output=True,timeout=20)
    with pytest.raises(ValueError):selection_expression([True])


@pytest.mark.parametrize('portrait',[False,True])
def test_all_host_grammars_are_seekable_and_runtime_pin_cannot_be_bypassed(tmp_path,portrait):
    require_runtime();from gateway.motion_contract import LAYOUTS
    work=tmp_path/'grammars';work.mkdir();(work/'tmp').mkdir()
    config={'width':720 if portrait else 1280,'height':1280 if portrait else 720,'total_frames':48*len(LAYOUTS)+49,'chunk_frames':96,
            'shots':[{'shot_num':i,'frames':97 if i==1 else 48,'portrait':portrait,'brand':'镜头语法实测'*13+'核对','motion':{'layout':layout,
                      'headline':'原文与现场核对'*4,'labels':['来源','核对','依据'],'focus':0}} for i,layout in enumerate(sorted(LAYOUTS),1)],
            'font':os.environ['NBPPT_HTML_FONT'],'font_sha256':os.environ['NBPPT_HTML_FONT_SHA256'],'ffmpeg':str(_find_ffmpeg())}
    (work/'config.json').write_text(json.dumps(config))
    environment={**os.environ,'TMPDIR':str(work/'tmp'),'NBPPT_CHROMIUM_SHA256':'0'*64}
    failed=subprocess.run([os.environ['NBPPT_HTML_NODE'],str(ROOT/'render.mjs'),str(work)],env=environment,capture_output=True,text=True,timeout=15)
    assert failed.returncode and 'pin missing or changed' in failed.stderr and not (work/'browser.json').exists()
    environment['NBPPT_CHROMIUM_SHA256']=os.environ['NBPPT_CHROMIUM_SHA256']
    result=subprocess.run([os.environ['NBPPT_HTML_NODE'],str(ROOT/'render.mjs'),str(work)],env=environment,capture_output=True,text=True,timeout=180)
    assert result.returncode==0,result.stderr
    ledger=json.loads((work/'chunks.json').read_text())
    assert len(ledger['chunks'])==10 and len(ledger['seek_determinism'])==len(LAYOUTS)==9
    one_frame=ledger['chunks'][1]
    assert one_frame['frame_count']==1 and len(one_frame['samples'])==2
    assert one_frame['samples'][0]==one_frame['samples'][1]
    assert ledger['network_requests']==[] and ledger['errors']==[]
