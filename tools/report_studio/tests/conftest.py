import pytest
from tools.report_studio.business_question import BusinessQuestion

@pytest.fixture
def business_question():
    return BusinessQuestion(question='现有业务表现是否偏离可比的正常基线？',decision='决定是否需要调查业务原因及调整经营动作。',normal_baseline='不同经营环节存在合理时滞，需要同口径基线才能判断异常。',evidence_status='open_question',supported_signal='当前材料提供若干经营观察，但尚未完整证明异常。',alternative_explanations=['正常时滞和统计口径差异'],missing_evidence=['同口径历史基线'],action_if_confirmed='定位原因后选择适用的经营调整。',rejected_premise='不能仅因两个环节不同就断言经营出了问题。')
