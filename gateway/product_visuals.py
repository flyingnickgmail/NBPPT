"""Operator-managed, tenant-bound product visuals. No upload, search or spending.

The configured store is an administrator trust boundary, not a client-supplied
approval assertion. Human records and their underlying rights evidence remain
local. Hashes prove which records were used, not the truth of a forged record.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import re

from PIL import Image

from gateway.exec_pitch_contract import canonical, digest, hash_id
from gateway.video_contract import _plain_text
from gateway.video_manuscript import read_json_text

KINDS={'crm_screenshot','brand_still','brand_broll','brand_logo'}
USES={'internal_review','client_pitch'}
SCOPE_FIELDS={'manifest_id','client_id','project_id','brand','intended_use'}
APPROVAL_FIELDS={'version','record_type','decision','reviewer','reviewed_at','valid_until',
    'authority_reference','asset_sha256','kind','owner','client_id','project_id','brand',
    'intended_uses','rights_holder','rights_evidence_sha256','brand_status','visible_brands',
    'vehicles_visible','privacy_status','frame_window'}


def identifier(value):
    return isinstance(value,str) and re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}',value) is not None


def plain(value,name,limit):
    if _plain_text(value,name,limit)!=value:raise ValueError('产品素材说明未规范化')


def validate_scope(scope):
    if (not isinstance(scope,dict) or set(scope)!=SCOPE_FIELDS or not hash_id(scope['manifest_id'])
            or not identifier(scope['client_id']) or not identifier(scope['project_id'])
            or not isinstance(scope['intended_use'],str) or scope['intended_use'] not in USES):
        raise ValueError('产品素材仅接受已登记清单编号、客户、项目、品牌和用途；不能提供路径或审批布尔值')
    plain(scope['brand'],'brand',60)


def timestamp(value):
    if not isinstance(value,str) or len(value)>40:raise ValueError('素材审批时间无效')
    try:result=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError('素材审批时间无效') from None
    if result.tzinfo is None:raise ValueError('素材审批时间必须包含时区')
    return result


def store_root():
    value=os.environ.get('NBPPT_PRODUCT_VISUAL_ROOT','');root=Path(value)
    if not value or not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError('缺少已审产品素材库；不能以生成界面、公共库存或品牌猜测替代')
    return root


def configured():
    try:store_root()
    except ValueError:return False
    return True


def resolve_visuals(value,spec):
    scope=value.get('product_visuals')
    if scope is None:return None
    validate_scope(scope)
    if spec.get('video_render_engine','html_chromium')!='html_chromium':
        raise ValueError('已审产品素材必须走HTML引擎，不可切换兼容剪辑器绕过素材检查')
    from gateway.exec_pitch_inputs import safe_file
    owner=spec['video_input_owner']
    if not hash_id(owner):raise ValueError('产品素材缺少当前账户身份')
    root=store_root()/owner/scope['manifest_id']
    raw=safe_file(root,'manifest.json',128*1024)
    manifest=read_json_text(raw.read_text())
    if digest(canonical(manifest))!=scope['manifest_id']:raise ValueError('产品素材清单摘要改变')
    fields={'version','owner','client_id','project_id','brand','allowed_uses','media_kind','assets'}
    if (not isinstance(manifest,dict) or set(manifest)!=fields or type(manifest['version']) is not int
            or manifest['version']!=1 or manifest['owner']!=owner
            or any(manifest[k]!=scope[k] for k in ('client_id','project_id','brand'))
            or manifest['media_kind']!=value['media_kind']):
        raise ValueError('产品素材不属于当前账户、客户、项目、品牌或媒体类别')
    uses=manifest['allowed_uses']
    if (not isinstance(uses,list) or not uses or len(uses)>len(USES)
            or any(not isinstance(u,str) or u not in USES for u in uses) or len(set(uses))!=len(uses)
            or scope['intended_use'] not in uses):raise ValueError('产品素材未授权本次用途')
    records=manifest['assets']
    if not isinstance(records,list) or not 1<=len(records)<=32:raise ValueError('产品素材清单为空或超过32项')
    by_id={}
    for item in records:
        if (not isinstance(item,dict) or set(item)!={'id','kind','sha256','extension','approval_sha256','source'}
                or not identifier(item['id']) or item['id'] in by_id or not isinstance(item['kind'],str) or item['kind'] not in KINDS
                or not hash_id(item['sha256']) or not hash_id(item['approval_sha256'])
                or item['extension'] not in (('mp4',) if item['kind']=='brand_broll' else ('png','jpg'))):
            raise ValueError('产品素材条目无效；仅接受有界本地图片和MP4')
        plain(item['source'],'asset source',400);by_id[item['id']]=item
    selected={};total_bytes=0;checked=set();intervals={};shot_refs={}
    for shot in value['shots']:
        asset_id=shot.get('product_asset_id')
        if not asset_id:continue
        if asset_id not in by_id:raise ValueError('镜头引用的已审产品素材缺失')
        shot_refs.setdefault(asset_id,[]).append(shot['shot_num'])
        if asset_id in selected:continue
        item=by_id[asset_id]
        approval_path=safe_file(root,f"evidence/{item['approval_sha256']}.json",64*1024)
        approval=read_json_text(approval_path.read_text())
        if digest(canonical(approval))!=item['approval_sha256']:raise ValueError('产品素材审批记录摘要改变')
        expected_type='test_fixture' if value['media_kind']=='synthetic_fixture' else 'human_record'
        if (not isinstance(approval,dict) or set(approval)!=APPROVAL_FIELDS
                or type(approval['version']) is not int or approval['version']!=1
                or approval['record_type']!=expected_type or approval['decision']!='approved'
                or approval['owner']!=owner or approval['asset_sha256']!=item['sha256']
                or approval['kind']!=item['kind']
                or any(approval[k]!=scope[k] for k in ('client_id','project_id','brand'))):
            raise ValueError('缺少绑定具体文件、账户及本次客户项目的人工审批记录')
        for key,limit in [('reviewer',100),('authority_reference',300),('rights_holder',160)]:plain(approval[key],key,limit)
        now=datetime.now(timezone.utc)
        if not timestamp(approval['reviewed_at'])<=now<timestamp(approval['valid_until']):
            raise ValueError('产品素材审批尚未生效或已过期')
        permitted=approval['intended_uses']
        if (not isinstance(permitted,list) or not permitted or len(permitted)>len(USES)
                or any(not isinstance(u,str) or u not in USES for u in permitted) or scope['intended_use'] not in permitted):
            raise ValueError('该文件的人工审批未覆盖本次用途')
        if (approval['brand_status']!='confirmed' or approval['visible_brands']!=[scope['brand']]
                or type(approval['vehicles_visible']) is not bool):
            raise ValueError('品牌未知、不符或混有其他品牌；需要逐项人工确认，未以OCR推断')
        if approval['privacy_status']!='cleared':raise ValueError('产品截图或品牌素材的隐私处理尚未确认')
        rights_sha=approval['rights_evidence_sha256']
        if not hash_id(rights_sha):raise ValueError('缺少独立权属或使用授权依据')
        rights=safe_file(root,f'evidence/{rights_sha}.txt',64*1024)
        if digest(rights.read_bytes())!=rights_sha or not rights.read_text().strip():raise ValueError('权属授权依据缺失或摘要改变')
        media=safe_file(root,f"media/{item['sha256']}.{item['extension']}",32_000_000 if item['kind']=='brand_broll' else 8_000_000)
        if item['sha256'] not in checked:
            total_bytes+=media.stat().st_size;checked.add(item['sha256'])
            if total_bytes>128_000_000 or digest(media.read_bytes())!=item['sha256']:raise ValueError('产品素材摘要改变或总量超过128MB')
        window=approval['frame_window']
        if item['kind']=='brand_broll':
            from worker.scene_assets import probe
            from fractions import Fraction
            info=probe(media);videos=[s for s in info['streams'] if s['codec_type']=='video']
            size=(1280,720) if spec['video_aspect_ratio']=='16:9' else (720,1280)
            if (len(videos)!=1 or videos[0]['codec_name']!='h264'
                    or (videos[0]['width'],videos[0]['height'])!=size
                    or Fraction(videos[0]['avg_frame_rate'])!=24
                    or not isinstance(window,list) or len(window)!=2
                    or any(type(n) is not int for n in window)
                    or not 0<=window[0]<window[1]<=int(videos[0].get('nb_frames',0))
                    or window[1]-window[0]>1440):
                raise ValueError('品牌实景必须是已审原生画幅、24帧MP4及有效的有界时间窗')
        else:
            with Image.open(media) as image:
                if (image.format!=('JPEG' if item['extension']=='jpg' else 'PNG') or getattr(image,'n_frames',1)!=1
                        or not 64<=image.width<=4096 or not 64<=image.height<=4096
                        or image.width*image.height>16_777_216 or window is not None):
                    raise ValueError('已审产品图片格式、尺寸或静态范围不符合要求')
                image.verify()
        selected[asset_id]={**item,'path':media,'approval':approval}
    for shot in value['shots']:
        asset_id=shot.get('product_asset_id')
        if not asset_id:continue
        item=selected[asset_id];layout=shot['motion']['layout']
        expected={'crm_screenshot':'crm_frame','brand_still':'broll_plate','brand_broll':'broll_plate','brand_logo':'closing'}
        if layout!=expected[item['kind']]:raise ValueError('产品素材种类与镜头版式不一致')
        if item['kind']=='brand_broll':
            frames=(shot['audio_samples']+1999)//2000+shot['lead_frames']+shot['tail_frames']
            begin,end=item['approval']['frame_window']
            if frames>end-begin:raise ValueError('已审品牌实景短于镜头，禁止循环、冻结或补帧')
            for a,b in intervals.get(item['sha256'],[]):
                if max(a,begin)<min(b,begin+frames):raise ValueError('品牌实景重复使用同一段已审时间窗')
            intervals.setdefault(item['sha256'],[]).append((begin,begin+frames))
    if not selected:raise ValueError('产品素材范围未绑定任何具体镜头')
    receipt={'version':1,'manifest_id':scope['manifest_id'],**{k:scope[k] for k in ('client_id','project_id','brand','intended_use')},
             'evidence_status':'TEST_FIXTURE_ONLY' if value['media_kind']=='synthetic_fixture' else 'REGISTERED_HUMAN_RECORD',
             'content_status':'NOT_REVIEWED','assets':[]}
    for key,item in selected.items():
        approval=item['approval']
        receipt['assets'].append({**{k:item[k] for k in ('id','kind','sha256','approval_sha256','source')},
            **{k:approval[k] for k in ('rights_holder','rights_evidence_sha256','brand_status','visible_brands','vehicles_visible','privacy_status','frame_window')},
            'shot_numbers':shot_refs[key]})
    return {'receipt':receipt,'assets':selected}


def verify_product_visuals(spec,root):
    from gateway.delivery import contained_file
    resolved=resolve_visuals(spec['exec_pitch_input'],spec)
    if resolved is None:return []
    path=contained_file(root,'product_visuals.json')
    if path.stat().st_size>128*1024 or read_json_text(path.read_text())!=resolved['receipt']:
        raise ValueError('产品素材交付记录与已审输入不一致')
    work=root.parent/'html-render'
    config=read_json_text(contained_file(work,'config.json').read_text())
    if len(config.get('shots',[]))!=len(spec['exec_pitch_input']['shots']):raise ValueError('产品素材渲染镜头数量改变')
    ledger=read_json_text(contained_file(root,'render_chunks.json').read_text())
    for shot,rendered in zip(spec['exec_pitch_input']['shots'],config['shots']):
        key=shot.get('product_asset_id')
        if not key:continue
        item=resolved['assets'][key]
        if (rendered.get('shot_num')!=shot['shot_num'] or rendered.get('product_asset_id')!=key
                or rendered.get('product_asset_sha256')!=item['sha256'] or rendered.get('approved_asset') is not True
                or rendered.get('product_kind')!=item['kind']):raise ValueError('产品素材未绑定真实渲染镜头')
        for chunk in ledger['chunks']:
            if chunk['shot_num']==shot['shot_num'] and (chunk.get('product_asset_id')!=key or chunk.get('product_asset_sha256')!=item['sha256']):
                raise ValueError('实际分块未绑定已审产品素材摘要')
        name=f"product-{item['sha256']}.{item['extension']}"
        copied=contained_file(work,name)
        if digest(copied.read_bytes())!=item['sha256']:raise ValueError('渲染使用的产品素材改变')
        if item['kind']!='brand_broll' and rendered.get('image_path')!=str(copied):
            raise ValueError('产品图片未进入可信渲染器')
    return [path]
