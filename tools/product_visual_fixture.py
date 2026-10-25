"""Synthetic cards for engineering checks, NEVER approvals for customer media."""
from pathlib import Path
import shutil

from PIL import Image,ImageDraw,ImageFont

from gateway.exec_pitch_contract import canonical,digest
from tools.exec_pitch_fixture import build_fixture


def build_product_fixture(registry,user,visual_store,second_kind='brand_still'):
    source,old_id,value=build_fixture(registry,user,6)
    owner=digest(user.encode());old=Path(registry)/owner/old_id
    build=Path(visual_store)/'fixture-build';(build/'media').mkdir(parents=True)
    (build/'evidence').mkdir()
    rights=b'SYNTHETIC TEST DATA ONLY. No product UI, vehicle photograph, customer logo or human commercial authorization.'
    rh=digest(rights);(build/f'evidence/{rh}.txt').write_bytes(rights)
    assets=[]
    for i,(key,kind) in enumerate([('screen-card','crm_screenshot'),('brand-card',second_kind)]):
        if kind=='brand_broll':
            media=next((old/'assets').glob('*.mp4'));extension='mp4'
        else:
            media=build/f'card-{i}.png';extension='png'
            image=Image.new('RGB',(1280,720),'#416F82' if i==0 else '#927341');draw=ImageDraw.Draw(image)
            for x in range(0,1280,160):draw.rectangle((x,0,x+70,720),fill='#355A69' if i==0 else '#705D3D')
            font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',44) if Path('/System/Library/Fonts/Supplemental/Arial.ttf').is_file() else ImageFont.load_default(size=40)
            draw.rectangle((45,245,1235,475),fill='#142D33');draw.text((75,280),'TEST FIXTURE - fixture-brand',fill='white',font=font)
            draw.text((75,355),'NOT PRODUCT UI / NOT CLIENT ASSET',fill='white',font=font);image.save(media)
        sha=digest(media.read_bytes());shutil.copyfile(media,build/f'media/{sha}.{extension}')
        approval={'version':1,'record_type':'test_fixture','decision':'approved','reviewer':'synthetic-test-record',
            'reviewed_at':'2000-01-01T00:00:00Z','valid_until':'2099-01-01T00:00:00Z',
            'authority_reference':'TEST_FIXTURE_ONLY: no human client approval is asserted',
            'asset_sha256':sha,'kind':kind,'owner':owner,'client_id':'fixture-client','project_id':'p2-fixture',
            'brand':'fixture-brand','intended_uses':['internal_review'],'rights_holder':'test-fixture-generator',
            'rights_evidence_sha256':rh,'brand_status':'confirmed','visible_brands':['fixture-brand'],
            'vehicles_visible':False,'privacy_status':'cleared','frame_window':[24,120] if kind=='brand_broll' else None}
        ah=digest(canonical(approval));(build/f'evidence/{ah}.json').write_bytes(canonical(approval))
        assets.append({'id':key,'kind':kind,'sha256':sha,'extension':extension,'approval_sha256':ah,
                       'source':'Generated synthetic test pattern; not a product or client-brand evidence source'})
    manifest={'version':1,'owner':owner,'client_id':'fixture-client','project_id':'p2-fixture','brand':'fixture-brand',
              'allowed_uses':['internal_review'],'media_kind':'synthetic_fixture','assets':assets}
    mid=digest(canonical(manifest));(build/'manifest.json').write_bytes(canonical(manifest))
    target=Path(visual_store)/owner/mid;target.parent.mkdir(parents=True,exist_ok=True);build.rename(target)
    value['title']='产品素材入口工程测试'
    value['evidence_boundary']='合成测试图卡与测试音调，不是产品界面、客户品牌素材、人工授权证据或内容验收。'
    value['product_visuals']={'manifest_id':mid,'client_id':'fixture-client','project_id':'p2-fixture',
                              'brand':'fixture-brand','intended_use':'internal_review'}
    for i,shot in enumerate(value['shots']):
        shot['product_asset_id']=assets[i]['id']
        shot['motion']={'layout':'crm_frame' if i==0 else 'closing' if second_kind=='brand_logo' else 'broll_plate',
                        'headline':'测试图卡，非产品界面' if i==0 else '不代表客户品牌授权',
                        'labels':['测试图卡','登记核对'],'focus':0}
    input_id=digest(canonical(value));new=old.parent/input_id;old.rename(new);(new/'input.json').write_bytes(canonical(value))
    return source,input_id,value
