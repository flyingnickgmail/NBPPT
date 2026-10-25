"""Source-grounded refinement of the existing warehouse rehearsal, before shots.

This is an authored example for the supplied material, not a general story model.
No provider, synthesis, observed business outcome or approval is generated.
"""
from copy import deepcopy

from gateway.exec_pitch_story import voice_identity,validate_story

PLAN = [
 ('problem','locate_gap','conditional_scenario','原库位没有包裹',['原库位','出库人员']),
 ('problem','withhold_judgment','limitation','空货位留下的是疑问',['空货位','仍待查证']),
 ('problem','form_question','conditional_scenario','下一步，凭什么判断',['记录线索','现场核对']),
 ('mechanism','join_records','source_statement','把散落线索连到同一包裹',['扫码记录','库位变更','交接备注']),
 ('mechanism','trace_origin','source_statement','沿来源找到先查的环节',['时间','操作者','原始记录']),
 ('mechanism','route_not_proof','limitation','有查证路线，仍未确认找回',['查证路线','现场结果']),
 ('mechanism','visit_handover','conditional_scenario','查最近交接，再到现场',['最近交接','现场核对']),
 ('mechanism','scan_identity','conditional_scenario','先核对标签，确认同一个包裹',['扫描标签','核对实物']),
 ('mechanism','escalate_unknown','conditional_scenario','仍然对不上：带着未知交接',['已核对','仍不清楚','负责人']),
 ('mechanism','block_guess','limitation','未确认，就不写成事实',['猜测','已确认事实']),
 ('mechanism','human_decision','source_statement','让线索可见，由责任人判断',['系统汇集线索','责任人核查']),
 ('mechanism','confirm_location','conditional_scenario','如果现场确认，再更正记录',['现场确认','更正库位','通知出库']),
 ('mechanism','append_basis','source_statement','追加处理依据，留下旧记录',['旧记录','更正依据']),
 ('mechanism','notify_then_verify','limitation','通知发出，核对还要继续',['更正通知','后续核对']),
 ('proof','review_trace','proposed_validation','哪些线索有效，哪里还缺记录',['有效线索','交接缺口','规则调整']),
 ('proof','separate_proof','limitation','机制可以演示，成效仍须实测',['机制演示','尚无实测']),
 ('proof','withhold_roi','limitation','没有实测依据，不填收益数字',['能力说明','实测依据']),
 ('close','pilot_roles','proposed_validation','先选一段交接，约定谁负责',['谁核对','谁确认','谁接收通知']),
 ('close','decide_scale','proposed_validation','让处理记录支持是否扩大的判断',['小范围试点','处理记录','是否扩大']),
 ('close','return_question','proposed_validation','把一次判断的依据留下',['同一个包裹','可追溯依据']),
]


def refine_parcel_story(parent,parent_id,spec):
    if len(parent['shots'])!=20:raise ValueError('本叙事仅覆盖既有20段仓库演绎，不自动套用其他材料')
    anchors=['出库人员','空货位','猜测','时间线','来源','证据','交接','同一个包裹','负责人','丢失',
             '责任','另一个货位','旧记录','核对','复盘','演示','收益','试点','扩大','依据']
    if any(token not in s['narration'] for token,s in zip(anchors,parent['shots'])):
        raise ValueError('当前声音稿不匹配既有故事，不能凭模板更换或重排口播')
    # Establish the causal argument and evidence boundary BEFORE assigning any
    # new visual action. The original approved narration remains immutable.
    def quotes(*numbers):
        return list(dict.fromkeys(q for n in numbers for q in parent['shots'][n-1]['source_quotes']))
    question='包裹不在原库位，下一步凭什么判断？'
    acts=[
        {'id':'problem','title':'问题','first_shot':1,'last_shot':3,
         'argument':'同一个待出库包裹在原库位没有找到，空货位不足以判定丢失，问题落在下一步如何查证。','source_quotes':quotes(1,2,3)},
        {'id':'mechanism','title':'查证机制','first_shot':4,'last_shot':14,
         'argument':'来源记录给出查证路线，现场核对同一标签。仍对不上时交接已知和未知；确认后才更正，追加依据并让接手人继续核对。','source_quotes':quotes(4,9,12,13)},
        {'id':'proof','title':'证据边界','first_shot':15,'last_shot':17,
         'argument':'来源支持的是功能与情境演绎。处理记录可以作为后续复盘依据，单次演示不能证明效率或收益，当前没有已观察的客户成效。','source_quotes':quotes(15,16,17)},
        {'id':'close','title':'试点收束','first_shot':18,'last_shot':20,
         'argument':'建议选一段真实交接流程，明确核对、确认和通知责任，再凭异常记录决定是否扩大。结尾回到同一个包裹与可追溯判断。','source_quotes':quotes(18,19,20)},
    ]
    story={'version':1,'source_sha256':parent['source_sha256'],'parent_input_id':parent_id,
           'voice_identity_sha256':voice_identity(parent),'question':question,'entity':'同一个包裹',
           'acts':acts,'turn':{'shot_num':9,'condition':'如果记录和现场仍然对不上','source_quotes':quotes(9)},
           'proof':{'kind':'source_grounded_demonstration','observed_outcomes':[],
                    'limitation':'复盘的目的不是凭单次演示证明效率提升，而是为后续改进留下依据。','source_quotes':quotes(16,17)},
           'ending':{'echo_question':question,'next_step':'建议的下一步是选择一段真实交接流程开展小范围试点',
                     'source_quotes':quotes(18,19,20),'status':'proposed_not_deployed'},'beats':[]}
    value=deepcopy(parent);value.pop('revision',None)
    value['causal_chain']=[a['argument'] for a in acts]
    value['evidence_boundary']='来源为产品功能与情境演绎，不是客户真实事件或已测得的成效。复用既有中文干声，画面为机制示意，不是客户界面。客户素材、品牌授权、最终审核和韩语译审仍缺。'
    for n,(act,action,kind,headline,labels) in enumerate(PLAN,1):
        story['beats'].append({'shot_num':n,'act':act,'action':action,'evidence_kind':kind,
                               'source_quotes':deepcopy(value['shots'][n-1]['source_quotes'])})
        value['shots'][n-1]['motion']={'layout':'parcel_story','headline':headline,'labels':labels,'focus':0}
    value['story']=story;validate_story(value,spec)
    return value
