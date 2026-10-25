"""Host-owned visual grammars. Client/model content remains bounded plain data."""
from gateway.video_contract import _plain_text, NUMBER_PATTERN

LAYOUTS={'title','comparison','process','architecture','task_hub','timeline','crm_frame','broll_plate','closing'}
# P6 is an explicit landscape/story profile, not a new generic/portrait layout.
STORY_LAYOUTS={'parcel_story'}


def validate_motion(value,source):
    if not isinstance(value,dict) or set(value)!={'layout','headline','labels','focus'}:
        raise ValueError('动态镜头只接受版式、文字、标签及焦点编号；不得提供HTML、脚本或路径')
    if value['layout'] not in LAYOUTS|STORY_LAYOUTS:
        raise ValueError('不支持的动态镜头版式')
    if _plain_text(value['headline'],'headline',28)!=value['headline']:
        raise ValueError('镜头标题未规范化')
    labels=value['labels']
    if not isinstance(labels,list) or not 2<=len(labels)<=4:
        raise ValueError('动态镜头需要2至4个可视对象')
    for label in labels:
        if _plain_text(label,'label',12)!=label:
            raise ValueError('镜头对象标签未规范化')
    if type(value['focus']) is not int or not 0<=value['focus']<len(labels):
        raise ValueError('动态镜头焦点编号无效')
    allowed=set(NUMBER_PATTERN.findall(source))
    if any(n not in allowed for n in NUMBER_PATTERN.findall(' '.join([value['headline'],*labels]))):
        raise ValueError('动态画面包含原文没有的数字')
    return value


def shot_motion(shot):
    # Older registered video inputs get the same trusted HTML B-roll plate.
    return shot.get('motion',{'layout':'broll_plate','headline':'','labels':['记录','核对'],'focus':0})
