"""Public-page access, per-item commercial permission and safe provenance."""
import asyncio
from copy import deepcopy
import json
import httpx
import pytest
from worker import scene_mixkit as mixkit, scene_discovery as discovery
from gateway.footage_contract import validate_source, description

QUERY={'query':'pottery','source_quote':'学员拉坯','action':'拉坯'}
URL='https://mixkit.co/free-stock-video/pottery-class-123/'

def item():
    return {'@type':'VideoObject','@id':URL+'#video','name':'Pottery class',
            'description':'Asian students making clay pots.', 'copyrightNotice':'Free',
            'license':mixkit.LICENSE,'duration':'PT0M20S','encodingFormat':'video/mp4',
            'contentUrl':'https://assets.mixkit.co/videos/123/123-1080.mp4'}

def document(video=None,commercial=True):
    text='<script type="application/ld+json">'+json.dumps({'@graph':[video or item()]})+'</script>'
    if commercial:
        text+='<p class="download-video-options__download-copy">Download this free stock video clip for commercial or personal use, under the <a href="/license/#videoFree" data-license="videoFree">Mixkit Stock Video Free License</a>.</p>'
    p=mixkit.Page();p.feed(text);return text,p


def test_keyless_public_search_checks_detail_before_acceptance(monkeypatch):
    monkeypatch.setenv('NBPPT_SCENE_SEARCH_PROVIDER','mixkit');monkeypatch.delenv('PEXELS_API_KEY',raising=False)
    discovery.preflight_search();calls=[]
    def respond(req):
        calls.append(req)
        assert 'Authorization' not in req.headers and 'cookie' not in req.headers
        if '/discover/' in req.url.path:
            return httpx.Response(301,headers={'location':'https://mixkit.co/free-stock-video/pottery/'})
        return httpx.Response(200,text=document(commercial=str(req.url)==URL)[0])
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            pending=await discovery.search_candidates([QUERY],client)
            assert pending[0]['license_pending'] is True and 'download_url' not in pending[0]
            rows=await mixkit.verify_selected(pending,client)
            assert len(rows)==1 and rows[0]['provider']=='mixkit'
            validate_source({**rows[0],'id':'mixkit-123-0'})
            assert description(rows[0])=='Pottery class. Asian students making clay pots.'
    asyncio.run(run());assert len(calls)==3


@pytest.mark.parametrize('defect',['restricted','missing_visible_license','unrelated_license','wrong_id','unsafe_media','preview','long','mismatch'])
def test_ambiguous_or_personal_only_license_is_rejected(defect):
    value=item();listed=deepcopy(value);commercial=True
    if defect=='restricted':value['copyrightNotice']='Mixkit Restricted License'
    if defect=='missing_visible_license':commercial=False
    if defect=='wrong_id':value['@id']=URL.replace('123','999')+'#video'
    if defect=='unsafe_media':listed['contentUrl']='https://assets.mixkit.co.attacker.test/file.mp4'
    if defect=='preview':listed['encodingFormat']='text/html'
    if defect=='long':value['duration']='PT99M0S'
    if defect=='mismatch':listed['copyrightNotice']='Mixkit Restricted License'
    _,page=document(value,commercial)
    if defect=='unrelated_license':
        page=mixkit.Page();page.feed(document(value,False)[0]+'<a data-license="videoFree" href="/license/#videoFree">Free</a> for commercial or personal use')
    assert mixkit.candidate(listed,page,QUERY) is None


@pytest.mark.parametrize('url',['http://mixkit.co/free-stock-video/a/','https://mixkit.co.evil.test/free-stock-video/a/','https://mixkit.co:8443/free-stock-video/a/','https://user@mixkit.co/free-stock-video/a/','https://mixkit.co/free-stock-video/a/?key=abc','https://mixkit.co/account/'])
def test_search_redirect_cannot_escape_public_surface(url):
    with pytest.raises(ValueError):mixkit.public_url(url)


def test_detail_content_rendition_is_used_instead_of_large_listing_or_embed_preview():
    listed=item();detail_item=item()
    detail_item['contentUrl']='https://assets.mixkit.co/videos/123/123-720.mp4'
    detail_item['embedUrl']='https://assets.mixkit.co/videos/123/123-360.mp4'
    _,page=document(detail_item)
    assert mixkit.candidate(listed,page,QUERY)['download_url']==detail_item['contentUrl']


def test_only_item_linked_tags_support_people_metadata():
    value=item();value['description']='People practice.';value['about']=[{'@id':'#asian'}]
    text,page=document(value)
    page.feed('<script type="application/ld+json">'+json.dumps({'@graph':[
        {'@type':'Thing','@id':'#asian','name':'Asian'},
        {'@type':'Thing','@id':'#unrelated','name':'Chinese'}]})+'</script>')
    result=mixkit.candidate(value,page,QUERY)
    assert 'Asian' in result['provider_description'] and 'Chinese' not in result['provider_description']


def test_detail_verification_is_bounded_and_never_accepts_restricted_content():
    pending={'id':'123','source_url':URL,'listing':item(),**QUERY}
    restricted=item();restricted['copyrightNotice']='Mixkit Restricted License'
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,text=document(restricted)[0]))) as client:
            assert await mixkit.verify_selected([pending],client)==[]
            with pytest.raises(ValueError):await mixkit.verify_selected([pending]*9,client)
    asyncio.run(run())
