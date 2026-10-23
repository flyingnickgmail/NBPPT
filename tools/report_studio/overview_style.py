"""Publication contract shared by model planning, rendering and preflight."""
import re
from .editorial_skill import skill_reference

VERSION = '3.2'
WIDTH = 1600
MARGIN = 96
MIN_NODE_SIZE = 44
TITLE_SIZE = 88
BODY_SIZE = 48
FOOTER_SIZE = 32


def publication_standard():
    return skill_reference('question-policy.md') + '\n' + skill_reference('cover-standard.md')


def rendering_standard():
    """Production receives the selected design, not every competing recipe."""
    return '''制作批准的分享信息图，竖版4:5。只执行资料中的当前art_direction、presentation和reader_design，不重新选题，不借用未选中的图种。
暖纸白#F5F1E9、石墨黑#252824、铜橙#B45F36；精细编辑线描，留白清楚。不要绿色、蓝色、广告效果、照片、人物摆拍、玩具三维模型、流程框图、正文卡片、按钮、粗箭头。
主视觉占一半以上，旁注贴近它解释的具体部位。标题清晰，正文和来源可读。只显示资料里实际提供的一个导语；不补回已省略的另一句。每条panel.statement及其status_text显示一次，boundary、来源和固定署名完整保留。
仅使用批准的文案，不印制作说明、字段名、长引文或校验记录。图形也不能增加新结论。没有实测数量时不加刻度、百分比、阈值或具名企业点位；具体轮廓、数量和面积均为概念示意，不能像已测得的样本或实际经营状态。
关系必须真正可见：范围内的对象完全在参照内，只有真正超出参照的部分强调；参考边界直接命名。不能把业务需求画成物理场地容量。概念对照不能画成已发生的前后变化，分析建议不能写成已经实施的公司成果。
制作一次完整原图。不要在图外再补正文，也不要使用与批准材料无关的图片。'''


def validate_publication_copy(plan):
    limits = [('标题', plan.title, 24), ('核心判断', plan.thesis, 42), ('结论边界', plan.boundary, 80)]
    for label, value, limit in limits:
        if len(value) > limit:
            raise ValueError(f'全景图标准：{label}超过{limit}字，应压缩文案，不能缩小字体')
    for panel in plan.panels:
        if len(panel.heading) > 10:
            raise ValueError('全景图标准：短注标题不超过10字；状态由程序另行标注')
        if len(panel.statement)>38:
            raise ValueError('全景图标准：每条关键判断不超过38字，请精简原意')
    if len(plan.panels)>4:
        raise ValueError('全景图标准：内容分享图最多4条关键判断，请合并次要内容')
    if 'AI辅助图解' in plan.boundary:
        raise ValueError('全景图标准：boundary只写内容限定；AI辅助图解由固定署名显示一次')
    labels = getattr(plan, 'visual_labels', [])
    if len(labels) > 5:
        raise ValueError('全景图标准：主图最多5个直接标签，减少术语与碎片信息')
    display = ' '.join([plan.title, plan.thesis, *labels,
                        *[p.heading + ' ' + p.statement for p in plan.panels]])
    if re.search(r'```|\b(?:def|function)\s+\w+|\b[A-Za-z_]\w*\(\s*(?:[a-z_]\w*(?:\s*[,=]\s*\w+)*)?\s*\)|\b\w+_\w+\b|=>', display):
        raise ValueError('全景图标准：面向普通读者的内容图片不能使用代码、函数或变量作为解释')


def validate_publication_structure(production):
    if production.mode != 'illustration':
        raise ValueError('全景图标准：用户不接受流程图；使用有材料依据的分析信息图，不能以流程模块、串联方框和连线作为主视觉')
