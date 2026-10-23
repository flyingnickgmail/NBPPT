import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import tools.report_studio.app as application
from tools.report_studio.app import ROOT, app
from tools.report_studio.models import ExportInput
from tools.report_studio.overview import attach
import tools.report_studio.overview_generation as generation


@pytest.fixture
def data():
    return ExportInput.model_validate_json((ROOT / 'sample.json').read_text())


def plan_for(data):
    return generation.OverviewPlan(question_review=dict(question='现有业务表现是否偏离可比的正常基线？',decision='决定是否需要调查业务原因及调整经营动作。',normal_baseline='不同经营环节存在合理时滞，需要同口径基线才能判断异常。',evidence_status='open_question',supported_signal='当前材料提供若干经营观察，但尚未完整证明异常。',alternative_explanations=['正常时滞和统计口径差异'],missing_evidence=['同口径历史基线'],action_if_confirmed='定位原因后选择适用的经营调整。',rejected_premise='不能仅因两个环节不同就断言经营出了问题。'), title=data.report.title, subtitle='先看证据，再验证改善', period='报告所列期间',
        thesis='需要从业务证据识别实际改善，不能用签约替代经营成果。',
        visual_metaphor='使用分层证据地图，把现有观察和待验证的业务问题分开放置。',
        layout_reason='材料包含观察与建议两种不同层级，需要在全景图里分别呈现。',
        art_direction='暖纸白、石墨黑与铜橙，使用精细线条表现证据的连接关系，保留清晰的中文和适当留白。',
        fact_refs=list(generation.evidence_catalog(data.report))[:2],
        presentation=dict(rendering='editorial_illustration', lead_copy='thesis', layout='annotated_hero',
            hero_anchor_labels=['现有观察','分析建议'],
            hero_description='以具名的观察与建议在同一主图中的不同位置和标记解释它们的证据性质，不把区域当数量。',
            panel_placements=[dict(panel_index=i,placement='在相应的具名观察旁直接放置短注，保留证据性质。') for i in range(2)],
            reading_order='先识别具名的观察差别，再看相邻解释，最后读受众启发。',
            selection_reason='采用连续的注释式主视觉说明证据关系，避免将全部解释排成段落和文档摘要。'),
        panels=[dict(heading='现有观察', statement='依据材料了解现有情况', status='inference' if i==1 else 'observed', section_index=i,
                     support_quote=s.paragraphs[0]) for i,s in enumerate(data.report.sections[:2])],
        boundary='分析建议不构成已经实现的业务成果，仍需验证。', source_ids=[],visual_labels=['现有观察','分析建议'],
        reader_design=dict(audience='普通业务读者',visual_grammar='evidence_landscape',
            encoding='以明确的证据类别和已披露或待验证状态解释判断边界，不把区域面积当作数量。',
            intended_understanding='读者应理解现有观察和分析建议分别需要什么证据。',implication_panel_index=1,plain_terms=[],
            anchors=[dict(label=label,role='entity',section_index=i,support_quote=data.report.sections[i].paragraphs[0])
                     for i,label in enumerate(['现有观察','分析建议'])],
            visual_proof=[dict(relation='comparison',anchor_labels=['现有观察','分析建议'],
                visible_encoding='用同位的实心和空心标记区分观察依据与有待验证的建议，位置不表示数量。',
                reader_readout='读者能够区分已经观察的事实和还需要验证的建议。',
                change_test='如果建议得到新的实证依据，所属证据类别及对应标记就需要一起改变。')]),
        selection={'candidates':[{'name':name,'encoding':'以不同分区与直接标签解释材料中的具体证据关系，不用大小表示数量。',
            'material_basis':'材料包含现有观察与尚待验证的判断，需要让读者同时看见依据和边界。',
            'misreading_risk':'线条不能被误读为已经成立的因果关系。'} for name in ['关系地图','并列对照','验证路径']],
            'selected':0,'reason':'选择关系地图，因为材料主要解释证据怎样支持判断，比物件陈列更容易辨认具体边界。'})


def test_plan_rejects_wrong_ref_quote_and_new_number(data):
    plan=plan_for(data)
    generation.validate_plan(plan,data)
    plan.panels[0].support_quote='不属于任何材料的逐字引文。'
    with pytest.raises(ValueError,match='逐字证据'):generation.validate_plan(plan,data)
    plan=plan_for(data);plan.fact_refs=['not-in-report']
    with pytest.raises(ValueError,match='不存在'):generation.validate_plan(plan,data)
    plan=plan_for(data);plan.thesis='利润已提高999999.123%'
    with pytest.raises(ValueError,match='数值'):generation.validate_plan(plan,data)


def test_reader_implication_is_existing_analysis_not_a_company_result(data):
    plan=plan_for(data)
    generation.validate_plan(plan,data)
    plan.reader_design.implication_panel_index=0
    with pytest.raises(ValueError,match='分析建议'):generation.validate_plan(plan,data)
    plan.reader_design.implication_panel_index=3
    with pytest.raises(ValueError,match='分析建议'):generation.validate_plan(plan,data)


def test_graphic_anchors_need_displayed_labels_and_original_evidence(data):
    plan=plan_for(data)
    generation.validate_plan(plan,data)
    plan.reader_design.anchors[0].label='没有画出的动作'
    with pytest.raises(ValueError,match='实际展示'):generation.validate_plan(plan,data)
    plan=plan_for(data);plan.reader_design.anchors[0].support_quote='材料从未提过这个动作，不能据此设计企业场景。'
    with pytest.raises(ValueError,match='逐字依据'):generation.validate_plan(plan,data)
    plan=plan_for(data);plan.reader_design.anchors[0].section_index=23
    with pytest.raises(ValueError,match='章节不存在'):generation.validate_plan(plan,data)


def test_graphic_proof_cannot_invent_or_repeat_its_material_anchors(data):
    plan=plan_for(data)
    plan.reader_design.visual_proof[0].anchor_labels=['现有观察','新造的结果']
    with pytest.raises(ValueError,match='图形论证'):generation.validate_plan(plan,data)
    plan.reader_design.visual_proof[0].anchor_labels=['现有观察','现有观察']
    with pytest.raises(ValueError,match='图形论证'):generation.validate_plan(plan,data)


def test_separate_evidence_excerpts_preserve_each_original_passage(data):
    first='来源说明了独立策略应约束操作权限。'
    last='验收应检查缺少批准时能否阻断并留存决定。'
    data.report.sections[0].paragraphs=[first,'中间另一段与这项具体判断无关。',last]
    plan=plan_for(data);plan.panels[0].support_quote=first+'\\n\\n'+last
    with pytest.raises(ValueError,match='逐字证据'):generation.validate_plan(plan,data)
    fixed=generation.separate_panel_quotes(plan,data)
    assert fixed.panels[0].support_quote==first and fixed.panels[0].additional_quotes==[last]
    assert plan.panels[0].additional_quotes==[]
    generation.validate_plan(fixed,data)
    plan.panels[0].support_quote=first+'\\n\\n'+'编造的另一段证据绝不能被自动修好。'
    with pytest.raises(ValueError,match='逐字证据'):
        generation.validate_plan(generation.separate_panel_quotes(plan,data),data)


def test_cross_chapter_evidence_has_explicit_and_verified_ownership(data):
    plan=plan_for(data);quote=data.report.sections[1].paragraphs[0]
    plan.panels[0].additional_quotes=[quote]
    with pytest.raises(ValueError,match='逐字证据'):generation.validate_plan(plan,data)
    fixed=generation.separate_panel_quotes(plan,data)
    assert fixed.panels[0].additional_quotes==[]
    assert fixed.panels[0].additional_evidence[0].section_index==1
    generation.validate_plan(fixed,data)
    fixed.panels[0].additional_evidence[0].section_index=0
    with pytest.raises(ValueError,match='声明章节'):generation.validate_plan(fixed,data)


@pytest.mark.anyio
async def test_failed_draft_must_pass_fresh_review_before_image(data,tmp_path,monkeypatch):
    plan=plan_for(data);(tmp_path/'draft-plan.json').write_text(plan.model_dump_json())
    calls=[]
    async def invoke(prompt,model,timeout,**kwargs):
        calls.append(model)
        if model is generation.OverviewPlan:return plan
        assert model is generation.PlanReview
        return generation.PlanReview(approved=False,issues=['核心关系未说明'],correction='重做解释')
    async def image(*args,**kwargs):raise AssertionError('未通过设计复核不能生图')
    async def progress(*args):pass
    monkeypatch.setattr(generation,'invoke',invoke);monkeypatch.setattr(generation,'generate_image',image)
    with pytest.raises(ValueError,match='复核未通过'):
        await generation.create_overview(data,tmp_path,progress)
    assert calls==[generation.PlanReview,generation.OverviewPlan,generation.PlanReview]


def test_only_selected_concept_reaches_image_tool_and_legacy_plan_still_loads(data):
    plan=plan_for(data)
    prompt=generation.render_prompt(plan,data)
    assert 'chosen_concept' in prompt and '关系地图' in prompt
    assert '"candidates"' not in prompt and '并列对照' not in prompt
    drawing=json.loads(prompt.split('设计资料：\n',1)[1].split('\n最终视觉要求',1)[0])
    assert set(drawing['panels'][0])=={'heading','statement','status_text'}
    assert 'support_quote' not in json.dumps(drawing)
    assert all(set(f)=={'label','value','basis'} for f in drawing['facts'])
    assert all(set(s)=={'label','date'} for s in drawing['sources'])
    assert 'plain_terms' not in drawing['reader_design']
    assert 'implication_panel_index' not in drawing['reader_design']
    assert drawing['reader_design']['anchors']==[{'label':'现有观察','role':'entity'},{'label':'分析建议','role':'entity'}]
    assert 'change_test' not in json.dumps(drawing)
    assert 'reader_readout' not in json.dumps(drawing)
    assert drawing['reader_design']['visual_proof'][0]['relation']=='comparison'
    assert drawing['reader_implication']==drawing['panels'][1]
    old=plan.model_dump();old.pop('selection');old.pop('reader_design')
    legacy=generation.OverviewPlan.model_validate(old)
    generation.validate_plan(legacy,data)
    assert legacy.selection is None


@pytest.mark.anyio
async def test_visual_rejection_retries_and_never_publishes_failed_image(data,tmp_path,monkeypatch):
    image=tmp_path/'image.png';Image.new('RGB',(40,50)).save(image)
    calls=[]
    async def invoke(prompt,model,timeout,images=None):
        if model is generation.OverviewPlan:return plan_for(data)
        if model is generation.PlanReview:return generation.PlanReview(approved=True,issues=[],correction='')
        if model is generation.PosterProduction:return generation.PosterProduction(mode='illustration',reason='该测试保留图片工具路径，用于验证失败复核不会替换原有报告内容。',nodes=[],edges=[],note='')
        assert images and Path(images[0]).is_file()
        calls.append(prompt)
        return generation.OverviewReview(approved=False,visible_facts=['错误数值'],issues=['负号丢失'],correction='恢复负号')
    async def imagegen(prompt,folder,attempt,reference=None):
        if attempt: assert '负号丢失' in prompt
        if attempt: assert reference.name == 'candidate-0.png'
        return image
    async def progress(*args):pass
    monkeypatch.setattr(generation,'invoke',invoke);monkeypatch.setattr(generation,'generate_image',imagegen)
    with pytest.raises(HTTPException) as exc:await generation.create_overview(data,tmp_path,progress)
    assert exc.value.status_code==422
    assert len(calls)==2
    assert not (tmp_path/'overview.png').exists()
    assert data.overview is None


@pytest.mark.anyio
async def test_word_accuracy_alone_cannot_approve_an_infographic(data,tmp_path,monkeypatch):
    plan=plan_for(data);plan.fact_refs=[]
    path=tmp_path/'image.png';Image.new('RGB',(40,50)).save(path)
    async def invoke(prompt,model,timeout,images=None):
        if model is generation.OverviewPlan:return plan
        if model is generation.PlanReview:return generation.PlanReview(approved=True,issues=[],correction='')
        return generation.OverviewReview(approved=True,visible_facts=['文字正确'],issues=[],correction='')
    async def imagegen(*args,**kwargs):return path
    async def progress(*args):pass
    monkeypatch.setattr(generation,'invoke',invoke);monkeypatch.setattr(generation,'generate_image',imagegen)
    with pytest.raises(HTTPException):await generation.create_overview(data,tmp_path,progress)
    review=json.loads((tmp_path/'review-1.json').read_text())
    assert not review['approved'] and any('实际图形逻辑' in issue for issue in review['issues'])
    assert not (tmp_path/'overview.png').exists()


@pytest.mark.anyio
@pytest.mark.parametrize('indices,matches',[([],True),([0],False),([0,0],True),([1],True)])
async def test_missing_failed_or_duplicate_graphic_proof_prevents_publish(data,tmp_path,monkeypatch,indices,matches):
    plan=plan_for(data);plan.fact_refs=[]
    path=tmp_path/'image.png';Image.new('RGB',(40,50)).save(path)
    async def invoke(prompt,model,timeout,images=None):
        if model is generation.OverviewPlan:return plan
        if model is generation.PlanReview:return generation.PlanReview(approved=True,issues=[],correction='')
        return generation.OverviewReview(approved=True,visible_facts=['文字正确'],issues=[],correction='',
            visual_logic='复核描述了图形的状态，但仍须逐项核对实际关系。',audience_takeaway='建议读者核查实际结果。',
            proof_checks=[dict(proof_index=i,visible_marks='图中可见实心与空心标记位于不同证据类别内。',matches=matches) for i in indices])
    async def imagegen(*args,**kwargs):return path
    async def progress(*args):pass
    monkeypatch.setattr(generation,'invoke',invoke);monkeypatch.setattr(generation,'generate_image',imagegen)
    with pytest.raises(HTTPException):await generation.create_overview(data,tmp_path,progress)
    review=json.loads((tmp_path/'review-1.json').read_text())
    assert not review['approved'] and any('图形论证' in issue for issue in review['issues'])
    assert not (tmp_path/'overview.png').exists()


@pytest.mark.anyio
async def test_design_coverage_failure_stops_before_image_generation(data,tmp_path,monkeypatch):
    plans=[]
    async def invoke(prompt,model,timeout,images=None):
        if model is generation.OverviewPlan:
            plans.append(prompt)
            return plan_for(data)
        return generation.PlanReview(approved=False,issues=['标题主题缺少正文支持'],correction='合并相关内容，为主要主题保留正文')
    async def imagegen(*args):raise AssertionError('设计未通过时不能生图')
    async def progress(*args):pass
    monkeypatch.setattr(generation,'invoke',invoke);monkeypatch.setattr(generation,'generate_image',imagegen)
    with pytest.raises(ValueError,match='文案复核'):await generation.create_overview(data,tmp_path,progress)
    assert len(plans)==2
    assert '标题主题缺少正文支持' in plans[1]
    assert not (tmp_path/'overview.png').exists()


@pytest.mark.anyio
async def test_image_output_must_belong_to_this_thread(tmp_path,monkeypatch):
    thread='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    home=tmp_path/'home';monkeypatch.setenv('CODEX_HOME',str(home))
    unrelated=tmp_path/'unrelated.png';Image.new('RGB',(30,40)).save(unrelated)
    folder=tmp_path/'job';folder.mkdir()
    async def subprocess(*cmd,**kwargs):
        assert 'features.shell_tool=false' in cmd and 'features.multi_agent=false' in cmd
        assert cmd[cmd.index('--sandbox')+1]=='read-only'
        class Process:
            returncode=0
            async def communicate(self,stdin):
                Path(cmd[cmd.index('--output-last-message')+1]).write_text(json.dumps({'image_path':str(unrelated)}))
                return json.dumps({'type':'thread.started','thread_id':thread}).encode(),None
        return Process()
    monkeypatch.setattr(generation.shutil,'which',lambda x:'/codex')
    monkeypatch.setattr(generation.asyncio,'create_subprocess_exec',subprocess)
    with pytest.raises(HTTPException) as exc:await generation.generate_image('test',folder,0)
    assert exc.value.status_code==502


@pytest.mark.anyio
async def test_image_job_resolves_relative_paths_before_changing_directory(tmp_path,monkeypatch):
    thread='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    home=tmp_path/'home';monkeypatch.setenv('CODEX_HOME',str(home))
    monkeypatch.chdir(tmp_path)
    folder=Path('job');folder.mkdir()
    reference=folder/'reference.png';Image.new('RGB',(30,40)).save(reference)
    result=home/'generated_images'/thread/'result.png'
    result.parent.mkdir(parents=True);Image.new('RGB',(30,40)).save(result)
    async def subprocess(*cmd,**kwargs):
        assert kwargs['cwd']==(tmp_path/'job')
        assert Path(cmd[cmd.index('--output-schema')+1]).is_file()
        assert Path(cmd[cmd.index('--image')+1])==reference.resolve()
        output=Path(cmd[cmd.index('--output-last-message')+1])
        assert output.is_absolute() and output.parent==kwargs['cwd']
        class Process:
            returncode=0
            async def communicate(self,stdin):
                output.write_text(json.dumps({'image_path':str(result)}))
                return json.dumps({'type':'thread.started','thread_id':thread}).encode(),None
        return Process()
    monkeypatch.setattr(generation.shutil,'which',lambda x:'/codex')
    monkeypatch.setattr(generation.asyncio,'create_subprocess_exec',subprocess)
    assert await generation.generate_image('test',folder,0,reference)==result


@pytest.mark.anyio
async def test_content_image_does_not_reselect_legacy_diagram_mode(data,tmp_path,monkeypatch):
    plan=plan_for(data);plan.fact_refs=[]
    (tmp_path/'resume-production.json').write_text(json.dumps(dict(mode='diagram',reason='此前结构图旧缓存不应成为当前内容图片的生产方式。',nodes=[],edges=[],note='',callouts=[])))
    image=tmp_path/'generated.png';Image.new('RGB',(40,50)).save(image)
    calls=[]
    async def invoke(prompt,model,timeout,images=None):
        if model is generation.OverviewPlan:return plan
        if model is generation.PlanReview:return generation.PlanReview(approved=True,issues=[],correction='')
        assert model is generation.OverviewReview, '不得重复询问被标准固定的生产方式'
        return generation.OverviewReview(approved=True,visible_facts=['现有观察'],issues=[],correction='',visual_logic='图中的分区区分已知证据与未知内容。',audience_takeaway='下方建议读者按相同口径核查。',proof_checks=[dict(proof_index=0,visible_marks='图中同位的实心与空心标记区分观察事实和分析建议。',matches=True)])
    async def imagegen(*args,**kwargs):calls.append('image');return image
    async def progress(*args):pass
    monkeypatch.setattr(generation,'invoke',invoke);monkeypatch.setattr(generation,'generate_image',imagegen)
    result=await generation.create_overview(data,tmp_path,progress)
    assert result.overview and calls==['image']
    assert json.loads((tmp_path/'production-plan-0-current.json').read_text())['mode']=='illustration'

def test_job_api_persists_output_and_refuses_missing_job(data,tmp_path,monkeypatch):
    monkeypatch.setattr(application,'OVERVIEW_JOBS_DIR',tmp_path/'jobs')
    image=tmp_path/'image.png';Image.new('RGB',(40,50)).save(image)
    async def create(data,folder,progress):
        await progress('checking','检查中')
        return attach(data,image,'这是从报告全部内容设计的概览图片，具体结论需要返回原文核对。')
    monkeypatch.setattr(application,'create_overview',create)
    with TestClient(app) as client:
        created=client.post('/api/overview',json=data.model_dump())
        assert created.status_code==202
        job=created.json()['id']
        for _ in range(20):
            status=client.get('/api/overview/'+job).json()
            if status['state']=='completed':break
        assert status['state']=='completed'
        result=client.get('/api/overview/'+job+'/result')
        assert result.status_code==200 and result.json()['overview']
        assert result.json()['report']==data.report.model_dump()
        application.previews.pop(job)
        assert client.get(status['preview_url']).status_code==200
        assert client.get(status['preview_url']+'/overview.png').content==image.read_bytes()
        assert client.get('/api/overview/not-a-job').status_code==404
        assert client.post('/api/overview',json=data.model_dump(),headers={'Origin':'https://example.org'}).status_code==403


def test_restarted_incomplete_job_is_failed(tmp_path,monkeypatch):
    monkeypatch.setattr(application,'OVERVIEW_JOBS_DIR',tmp_path)
    job='a'*32;(tmp_path/job).mkdir()
    (tmp_path/job/'status.json').write_text(json.dumps({'id':job,'state':'generating','message':'生成中'}))
    with TestClient(app) as client:
        assert client.get('/api/overview/'+job).json()['state']=='failed'
        assert client.get('/api/overview/'+job+'/result').status_code==409


def test_failed_job_preserves_original_and_releases_slot(data,tmp_path,monkeypatch):
    monkeypatch.setattr(application,'OVERVIEW_JOBS_DIR',tmp_path)
    original=data.model_dump()
    async def fail(*args):raise HTTPException(422,'图片中的现金流负号缺失')
    monkeypatch.setattr(application,'create_overview',fail)
    with TestClient(app) as client:
        created=client.post('/api/overview',json=data.model_dump());job=created.json()['id']
        for _ in range(20):
            status=client.get('/api/overview/'+job).json()
            if status['state']=='failed':break
        assert status['state']=='failed'
        assert '负号' in status['message']
        assert client.get('/preview/'+job).status_code==404
        assert not (tmp_path/job/'report.html').exists()
        assert not application.lock.locked()
        assert data.model_dump()==original


@pytest.mark.parametrize('style_version,expected', [(application.OVERVIEW_STANDARD_VERSION, True), ('2.7', False), ('2.6', False), ('2.5', False), ('2.4', False), ('2.3', False), ('2.2', False), ('2.1', False), ('2.0', False), ('1.0', False)])
def test_retry_reuses_approved_design_only_for_identical_source(data,tmp_path,monkeypatch,style_version,expected):
    monkeypatch.setattr(application,'OVERVIEW_JOBS_DIR',tmp_path)
    old=tmp_path/('b'*32);old.mkdir()
    (old/'status.json').write_text(json.dumps({'state':'failed'}))
    (old/'publication-version.txt').write_text(style_version)
    (old/'input.json').write_text(data.model_dump_json())
    (old/'design-plan-0.json').write_text(plan_for(data).model_dump_json())
    (old/'plan-review-0.json').write_text(json.dumps({'approved':True,'issues':[],'correction':''}))
    (old/'review-1.json').write_text(json.dumps({'approved':False,'issues':['图标方向误导'],'correction':'修改图标'}))
    Image.new('RGB',(40,50)).save(old/'candidate-1.png')
    resumed=[]
    async def create(data,folder,progress):
        resumed.append((folder/'resume-image.png').is_file())
        return attach(data,old/'candidate-1.png','这是一张来自原报告的完整全景图，用于验证内容一致时恢复图片设计。')
    monkeypatch.setattr(application,'create_overview',create)
    with TestClient(app) as client:
        for content in [data.content,data.content+'\n']:
            payload=data.model_dump();payload['content']=content
            job=client.post('/api/overview',json=payload).json()['id']
            for _ in range(20):
                if client.get('/api/overview/'+job).json()['state']=='completed':break
    assert resumed==[expected,False]


def composite_for(data):
    plan=plan_for(data)
    plan.panels.append(plan.panels[0].model_copy(deep=True))
    plan.presentation.panel_placements.append(generation.SharePlacement(panel_index=2,placement='在解释观察差别的具体部位放置独立业务短注。'))
    rd=plan.reader_design;rd.visual_grammar='evidence_composite'
    rd.visual_proof.append(rd.visual_proof[0].model_copy(deep=True))
    rd.composition_parts=[generation.OverviewCompositionPart(role=role,
        visible_relation='通过相邻但性质不同的业务观察边界解释哪些情况需要分别核对。',
        anchor_labels=['现有观察','分析建议'],panel_indices=[index])
        for role,index in [('signal',0),('explanation',2),('implication',1)]]
    return plan


def test_composite_requires_visible_explanation_not_just_large_numbers(data):
    plan=composite_for(data);generation.validate_plan(plan,data)
    plan.reader_design.composition_parts.pop(1)
    with pytest.raises(ValueError,match='数据信号'):generation.validate_plan(plan,data)
    plan=composite_for(data);plan.reader_design.composition_parts[1].panel_indices=[0]
    with pytest.raises(ValueError,match='遗漏'):generation.validate_plan(plan,data)
    plan.panels.pop()
    plan.presentation.panel_placements.pop()
    with pytest.raises(ValueError,match='独立的业务解释'):generation.validate_plan(plan,data)


def test_composite_cannot_discard_or_invent_explanation_anchors(data):
    plan=composite_for(data);plan.reader_design.composition_parts[1].anchor_labels=['新增的去向']
    with pytest.raises(ValueError,match='原文锚点'):generation.validate_plan(plan,data)
    plan=composite_for(data);plan.reader_design.composition_parts[1].panel_indices=[99]
    with pytest.raises(ValueError,match='不存在'):generation.validate_plan(plan,data)
    plan=composite_for(data);plan.reader_design.visual_proof.pop()
    with pytest.raises(ValueError,match='两项图形论证'):generation.validate_plan(plan,data)


def test_composite_relation_design_reaches_image_prompt(data):
    plan=composite_for(data)
    plan.reader_design.chart_caption='各指标分别使用自身基期，不推算转化率。'
    prompt=generation.render_prompt(plan,data)
    drawing=json.loads(prompt.split('设计资料：\n',1)[1].split('\n最终视觉要求',1)[0])
    assert [p['role'] for p in drawing['reader_design']['composition_parts']]==['signal','explanation','implication']
    assert drawing['reader_design']['chart_caption']==plan.reader_design.chart_caption
    assert drawing['publication_footer']==dict(brand='友车科技 · 研究图解',disclosure='AI辅助图解 · 依据输入报告整理')
    from tools.report_studio.quantitative_poster import select_chart
    assert select_chart(plan,data) is None


def layout_revision_for(plan):
    return generation.OverviewLayoutRevision(
        visual_metaphor=plan.visual_metaphor,layout_reason=plan.layout_reason,
        art_direction='通过具名观察的时间对齐解释业务与记录的区别，保留全部已批准文字和必要边界。',
        encoding=plan.reader_design.encoding,
        composition_parts=plan.reader_design.composition_parts,
        visual_proof=plan.reader_design.visual_proof)


@pytest.mark.anyio
async def test_layout_redesign_preserves_all_facts_and_citations(data,monkeypatch):
    plan=composite_for(data);before=plan.model_dump()
    async def invoke(prompt,*args,**kwargs):
        assert 'material_context' in prompt and data.report.title in prompt
        return layout_revision_for(plan)
    monkeypatch.setattr(generation,'invoke',invoke)
    review=generation.OverviewReview(approved=False,redesign_required=True,visible_facts=[],
        issues=['原构图没有解释业务关系'],correction='改用可辨认的关系表达')
    result=await generation.revise_visual_reasoning(plan,data,review)
    assert plan.model_dump()==before
    for key in ('title','thesis','panels','boundary','fact_refs','source_ids','visual_labels'):
        assert result.model_dump()[key]==before[key]
    assert result.reader_design.anchors==plan.reader_design.anchors
    assert result.art_direction!=plan.art_direction


@pytest.mark.anyio
async def test_layout_redesign_rejects_invented_relation_anchor(data,monkeypatch):
    plan=composite_for(data);revision=layout_revision_for(plan).model_copy(deep=True)
    revision.visual_proof[0].anchor_labels=['现有观察','编造的新增结果']
    async def invoke(*args,**kwargs):return revision
    monkeypatch.setattr(generation,'invoke',invoke)
    review=generation.OverviewReview(approved=False,visible_facts=[],issues=['表达错误'],correction='重新设计')
    with pytest.raises(ValueError,match='图形论证'):
        await generation.revise_visual_reasoning(plan,data,review)


@pytest.mark.anyio
@pytest.mark.parametrize('unrelated',[False,True])
async def test_rejected_concept_is_redesigned_before_second_image(data,tmp_path,monkeypatch,unrelated):
    plan=composite_for(data);plan.fact_refs=[]
    path=tmp_path/'image.png';Image.new('RGB',(40,50)).save(path)
    image_prompts=[];reviews=[];revisions=[];references=[]
    async def invoke(prompt,model,timeout,images=None):
        if model is generation.OverviewPlan:return plan
        if model is generation.PlanReview:return generation.PlanReview(approved=True,issues=[],correction='')
        if issubclass(model,generation.OverviewLayoutRevision):
            revisions.append(prompt);return layout_revision_for(plan)
        reviews.append(prompt);approved=len(reviews)>1
        return generation.OverviewReview(approved=approved,redesign_required=not approved,
            unrelated_image=unrelated and not approved,
            visible_facts=['分析建议仍需业务验证'],issues=[] if approved else ['原构图没有解释关系'],correction='重新设计表达',
            visual_logic='可见不同观察位置的状态差异，区分观察事实和待验证结论。',audience_takeaway='核对真实业务记录。',
            proof_checks=[dict(proof_index=i,visible_marks='同位标记及其标签解释观察依据与待验证判断之间的区别。',matches=approved) for i in range(2)])
    async def imagegen(prompt,*args,**kwargs):
        image_prompts.append(prompt);references.append(kwargs.get('reference'));return path
    async def progress(*args):pass
    monkeypatch.setattr(generation,'invoke',invoke);monkeypatch.setattr(generation,'generate_image',imagegen)
    result=await generation.create_overview(data,tmp_path,progress)
    assert result.overview and len(revisions)==(0 if unrelated else 1) and len(image_prompts)==2
    if unrelated:
        assert image_prompts[1]==image_prompts[0], 'Unrelated output must regenerate the approved design'
    else:
        assert layout_revision_for(plan).art_direction in image_prompts[1]
        assert (tmp_path/'revised-layout-0.json').exists()
    assert references==[None,None], 'Rejected composition must not anchor the replacement image'


def test_share_composition_preserves_every_panel_and_uses_grounded_anchors(data):
    plan=plan_for(data)
    generation.validate_plan(plan,data)
    plan.presentation.panel_placements.pop()
    with pytest.raises(ValueError,match='唯一位置'):generation.validate_plan(plan,data)
    plan=plan_for(data);plan.presentation.hero_anchor_labels=['现有观察','编造阈值']
    with pytest.raises(ValueError,match='材料锚点'):generation.validate_plan(plan,data)
    plan=plan_for(data);plan.presentation.rendering='exact_reference'
    with pytest.raises(ValueError,match='不得硬套'):generation.validate_plan(plan,data)


def test_share_prompt_prints_one_lead_preserving_all_panels_and_boundary(data):
    plan=plan_for(data)
    prompt=generation.render_prompt(plan,data)
    drawing=json.loads(prompt.split('设计资料：\n',1)[1].split('\n最终视觉要求',1)[0])
    assert 'subtitle' not in drawing and drawing['thesis']==plan.thesis
    assert len(drawing['panels'])==len(plan.panels)
    assert drawing['boundary']==plan.boundary
    assert drawing['presentation']['hero_anchor_labels']==plan.visual_labels


def test_selected_candidate_cannot_restore_rejected_geometry(data):
    plan=plan_for(data)
    plan.selection.candidates[plan.selection.selected].encoding='旧的两根横条只是初稿布局，不能覆盖已经修订的主视觉与阅读层次。'
    prompt=generation.render_prompt(plan,data)
    drawing=json.loads(prompt.split('设计资料：\n',1)[1].split('\n最终视觉要求',1)[0])
    assert drawing['chosen_concept']['encoding']==plan.reader_design.encoding
    assert '旧的两根横条' not in prompt


def test_production_brief_does_not_reintroduce_competing_recipes(data):
    plan=plan_for(data)
    prompt=generation.render_prompt(plan,data)
    assert '不重新选题' in prompt and '#B45F36' in prompt
    assert '2.9 · 分享图' not in prompt and '3.0 · 信号' not in prompt
    assert 'question_review' not in prompt
    assert plan.art_direction in prompt


def test_retry_keeps_approved_plan_but_never_reuses_unrelated_image(data,tmp_path,monkeypatch):
    monkeypatch.setattr(application,'OVERVIEW_JOBS_DIR',tmp_path)
    old=tmp_path/('c'*32);old.mkdir()
    (old/'status.json').write_text(json.dumps({'state':'failed'}))
    (old/'publication-version.txt').write_text(application.OVERVIEW_STANDARD_VERSION)
    (old/'input.json').write_text(data.model_dump_json())
    (old/'design-plan-0.json').write_text(plan_for(data).model_dump_json())
    (old/'plan-review-0.json').write_text(json.dumps({'approved':True,'issues':[]}))
    (old/'review-1.json').write_text(json.dumps({'approved':False,'unrelated_image':True,'issues':['图片完全跑题']}))
    Image.new('RGB',(40,50)).save(old/'candidate-1.png')
    resumed=[]
    async def create(data,folder,progress):
        resumed.append(((folder/'resume-plan.json').is_file(),(folder/'resume-image.png').is_file()))
        return attach(data,old/'candidate-1.png','模拟附件只用于检测恢复路径是否错误复用了无关图片，不代表真实图文审核。')
    monkeypatch.setattr(application,'create_overview',create)
    with TestClient(app) as client:
        job=client.post('/api/overview',json=data.model_dump()).json()['id']
        for _ in range(20):
            if client.get('/api/overview/'+job).json()['state']=='completed':break
    assert resumed==[(True,False)]
