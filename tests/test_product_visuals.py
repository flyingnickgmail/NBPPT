"""P2 authority, local-byte integrity, explicit gaps and actual trusted rendering."""
import asyncio
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess

import httpx
import pytest

from gateway.exec_pitch_contract import canonical,digest,validate_input
from gateway.exec_pitch_inputs import load_input
from gateway.product_visuals import resolve_visuals,verify_product_visuals
from tools.product_visual_fixture import build_product_fixture
from test_exec_pitch import spec
from test_security_delivery import manager,KEY_A,KEY_B,balance


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    registry=tmp_path/'registry';visuals=tmp_path/'product-visuals'
    source,input_id,value=build_product_fixture(registry,'a',visuals)
    monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry));monkeypatch.setenv('NBPPT_PRODUCT_VISUAL_ROOT',str(visuals))
    current={**spec(source,6,input_id,digest(b'a')),'video_render_engine':'html_chromium'}
    return registry,visuals,value,current


def rewrite_store(prepared,change):
    registry,visuals,value,current=prepared
    owner=current['video_input_owner'];root=visuals/owner/value['product_visuals']['manifest_id']
    manifest=json.loads((root/'manifest.json').read_text())
    for item in manifest['assets']:
        path=root/f"evidence/{item['approval_sha256']}.json";approval=json.loads(path.read_text())
        change(approval,item,manifest)
        item['approval_sha256']=digest(canonical(approval));(root/f"evidence/{item['approval_sha256']}.json").write_bytes(canonical(approval))
    mid=digest(canonical(manifest));(root/'manifest.json').write_bytes(canonical(manifest))
    if mid!=root.name:root.rename(root.parent/mid)
    value['product_visuals']['manifest_id']=mid
    return value,current


def test_approved_records_are_independent_of_narrative_and_remain_fixture_only(prepared):
    registry,visuals,value,current=prepared
    result=load_input(current['video_input_owner'],current['video_input_id'],current)[0]
    facts=resolve_visuals(result,current)['receipt']
    assert facts['evidence_status']=='TEST_FIXTURE_ONLY' and facts['content_status']=='NOT_REVIEWED'
    assert [a['kind'] for a in facts['assets']]==['crm_screenshot','brand_still']
    assert all(a['rights_evidence_sha256'] and a['approval_sha256'] for a in facts['assets'])
    assert str(visuals) not in json.dumps(facts)


@pytest.mark.parametrize('change',[
    lambda a,i,m:a.update(decision='pending'),
    lambda a,i,m:a.update(record_type='human_record'),
    lambda a,i,m:a.update(reviewer=''),
    lambda a,i,m:a.update(rights_holder=''),
    lambda a,i,m:a.update(authority_reference=''),
    lambda a,i,m:a.update(brand_status='unknown'),
    lambda a,i,m:a.update(visible_brands=['competitor']),
    lambda a,i,m:a.update(visible_brands=['fixture-brand','competitor']),
    lambda a,i,m:a.update(privacy_status='unknown'),
    lambda a,i,m:a.update(vehicles_visible='false'),
    lambda a,i,m:a.update(valid_until='2001-01-01T00:00:00Z'),
    lambda a,i,m:a.update(reviewed_at='2098-01-01T00:00:00Z'),
    lambda a,i,m:a.update(valid_until='2099-01-01'),
    lambda a,i,m:a.update(owner='0'*64),
    lambda a,i,m:a.update(client_id='other-client'),
    lambda a,i,m:a.update(project_id='other-project'),
    lambda a,i,m:a.update(intended_uses=['client_pitch']),
    lambda a,i,m:a.update(asset_sha256='0'*64),
    lambda a,i,m:a.update(rights_evidence_sha256='0'*64),
    lambda a,i,m:i.update(extension='svg'),
    lambda a,i,m:i.update(file='/etc/passwd'),
])
def test_unapproved_wrong_brand_wrong_scope_and_unsafe_media_are_blocked(prepared,change):
    value,current=rewrite_store(prepared,change)
    with pytest.raises(ValueError):resolve_visuals(value,current)


@pytest.mark.parametrize('change',[
    lambda v:v['product_visuals'].update(approved=True),
    lambda v:v['product_visuals'].update(manifest_id='../../anything'),
    lambda v:v['product_visuals'].update(intended_use=[]),
    lambda v:v['shots'][0].update(product_asset_id='../../anything'),
    lambda v:v['shots'][0].pop('product_asset_id'),
    lambda v:v['shots'][1].pop('product_asset_id'),
    lambda v:v.pop('product_visuals'),
    lambda v:v['shots'][0].update(approved=True),
])
def test_client_cannot_approve_or_choose_paths_or_publish_missing_slots(prepared,change):
    _,_,value,current=prepared;change(value)
    with pytest.raises(ValueError):validate_input(value,current)


def test_cross_account_manifest_substitution_fixture_promotion_and_engine_bypass_are_blocked(prepared,monkeypatch):
    _,visuals,value,current=prepared
    with pytest.raises(ValueError):resolve_visuals(value,{**current,'video_input_owner':digest(b'b')})
    with pytest.raises(ValueError):resolve_visuals({**value,'media_kind':'approved_local'},current)
    with pytest.raises(ValueError):resolve_visuals(value,{**current,'video_render_engine':'registered_video'})
    foreign=copy.deepcopy(value);foreign['product_visuals']['brand']='other-brand'
    with pytest.raises(ValueError):resolve_visuals(foreign,current)
    monkeypatch.delenv('NBPPT_PRODUCT_VISUAL_ROOT')
    with pytest.raises(ValueError,match='缺少已审'):resolve_visuals(value,current)


def test_selected_asset_and_evidence_tampering_or_symlink_fails(prepared):
    _,visuals,value,current=prepared;root=visuals/current['video_input_owner']/value['product_visuals']['manifest_id']
    record=json.loads((root/'manifest.json').read_text())['assets'][0]
    media=root/f"media/{record['sha256']}.png";original=media.read_bytes();media.write_bytes(original+b'changed')
    with pytest.raises(ValueError,match='摘要'):resolve_visuals(value,current)
    media.write_bytes(original);backup=media.with_suffix('.original');media.rename(backup);media.symlink_to(backup)
    with pytest.raises(ValueError,match='不安全'):resolve_visuals(value,current)


def require_runtime():
    if not os.environ.get('NBPPT_CHROMIUM_SHA256'):pytest.skip('optional pinned HTML runtime not configured')


@pytest.mark.parametrize('second_kind',['brand_still','brand_broll','brand_logo'])
def test_actual_html_product_cards_broll_and_logo_keep_source_bytes_and_final_gate(tmp_path,monkeypatch,second_kind):
    require_runtime()
    from worker.html_motion_renderer import render_chunks
    from worker.video_subtitles import _find_ffmpeg
    from PIL import Image
    import numpy as np
    registry=tmp_path/'registry';visuals=tmp_path/'visuals'
    source,input_id,value=build_product_fixture(registry,'a',visuals,second_kind)
    monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry));monkeypatch.setenv('NBPPT_PRODUCT_VISUAL_ROOT',str(visuals))
    current={**spec(source,6,input_id,digest(b'a')),'video_render_engine':'html_chromium','video_width':1280,'video_height':720}
    value,timeline,registered=load_input(current['video_input_owner'],input_id,current)
    job=tmp_path/'video_abcdef1234';(job/'staging/assets').mkdir(parents=True)
    picture=render_chunks(job,current,value,timeline,registered,str(_find_ffmpeg()))
    current.update(exec_pitch_input=value,exec_pitch_timeline=timeline)
    receipt=resolve_visuals(value,current)['receipt'];(job/'staging/product_visuals.json').write_text(json.dumps(receipt))
    assert verify_product_visuals(current,job/'staging')
    # Real encoded frame must contain the blue test card; a fake/placeholder UI
    # or parcel-only template would have the dark backdrop instead.
    frame=job/'decoded.png';subprocess.run(['ffmpeg','-v','error','-ss','1','-i',str(picture),'-frames:v','1',str(frame)],check=True)
    with Image.open(frame) as image:
        pixels=np.asarray(image,dtype=np.int16);blue=(pixels[:,:,2]>pixels[:,:,0]+25)&(pixels[:,:,2]>70)
        assert blue[245:545,350:930].mean()>.20
    chunks=json.loads((job/'staging/render_chunks.json').read_text())
    assert all(c.get('product_asset_sha256') for c in chunks['chunks'])
    copied=next((job/'html-render').glob('product-*.png'));copied.write_bytes(b'changed')
    with pytest.raises(ValueError,match='素材改变'):verify_product_visuals(current,job/'staging')


def test_missing_approval_denied_before_freeze_race_refunds_and_retry_serves_scoped_receipt(prepared,manager,monkeypatch):
    require_runtime()
    from gateway import main,mcp_server
    from gateway.auth import authenticate_key
    from gateway.mcp_server import PresentationJobs
    from worker import worker_api,video_generation
    _,visuals,value,current=prepared
    resolved=resolve_visuals(value,current);item=next(iter(resolved['assets'].values()))
    store=visuals/current['video_input_owner']/value['product_visuals']['manifest_id']
    evidence=store/f"evidence/{item['approval']['rights_evidence_sha256']}.txt";saved=evidence.read_bytes()
    monkeypatch.setattr(worker_api,'WORKSPACE_JOBS_DIR',manager.jobs_root)
    secret='sandbox-'+40*'s';monkeypatch.setattr(worker_api,'WORKER_SECRET',secret)
    monkeypatch.setattr(mcp_server,'get_runtime_settings',lambda:{'overseas_worker_url':'http://worker','overseas_worker_secret':secret})
    original_client=httpx.AsyncClient
    monkeypatch.setattr(mcp_server.httpx,'AsyncClient',lambda **kw:original_client(transport=httpx.ASGITransport(app=worker_api.app),**kw))
    package=video_generation.package_video
    def revoke_after_admission(*args,**kwargs):
        evidence.write_bytes(b'changed-after-admission');return package(*args,**kwargs)
    async def run():
        jobs=PresentationJobs(manager);monkeypatch.setattr(main,'mcp_jobs',jobs)
        principal=await authenticate_key(manager,KEY_A)
        payload={'source':current['original_prompt_cn'],'request_id':'p2-missing-evidence','task_type':'video',
            'video_duration_sec':6,'video_preset':'exec_pitch','video_input_id':current['video_input_id'],
            'video_voice':'approved_local','video_visual_mode':'registered_local','execution_mode':'auto'}
        async with original_client(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as client:
            evidence.write_bytes(b'not-an-approval')
            response=await client.post('/api/jobs',headers={'Authorization':'Bearer '+KEY_A},json=payload)
            assert response.status_code==422 and balance(manager)==(2000,0)
            evidence.write_bytes(saved);monkeypatch.setattr(video_generation,'package_video',revoke_after_admission)
            response=await client.post('/api/jobs',headers={'Authorization':'Bearer '+KEY_A},json={**payload,'request_id':'p2-revoked-after-admission'})
            assert response.status_code==200;failed=response.json()['job_id']
            while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
            assert (await jobs.status(principal,failed))['status']=='FAILED' and balance(manager)==(2000,0)
            evidence.write_bytes(saved);monkeypatch.setattr(video_generation,'package_video',package)
            retry=await jobs.retry(principal,failed,'p2-same-input-retry')
            while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
            state=await jobs.status(principal,retry['job_id'])
            assert state['status']=='COMPLETED',await manager.get_job(retry['job_id'],'a')
            assert balance(manager)==(1944,0)
            artifacts=await jobs.artifacts(principal,retry['job_id']);url=artifacts['artifacts']['product_visuals_url']
            assert url and artifacts['content_status']=='NOT_REVIEWED'
            assert (await client.get(url)).status_code==401
            assert (await client.get(url,headers={'Authorization':'Bearer '+KEY_B})).status_code==404
            response=await client.get(url,headers={'Authorization':'Bearer '+KEY_A})
            assert response.status_code==200 and response.json()['evidence_status']=='TEST_FIXTURE_ONLY'
            assert str(visuals) not in response.text
            output=manager.jobs_root/retry['job_id']/'output/product_visuals.json';output.write_text('{}')
            with pytest.raises(ValueError):await jobs.artifacts(principal,retry['job_id'])
    asyncio.run(run())
