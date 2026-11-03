"""Captured new sage question and restarting on an already opened quiz."""
import pytest
from chao2.anomalies import sage_answer,sage_question
from chao2.policy import TaskBlocked,UserStopped
from chao2.workflows import is_world
from test_configuration import captured,daily
from test_anomalies import SageReplay


def test_dominance_question_uses_unique_visible_answer_regardless_of_position():
    s=captured('v0915-sage-dominance',True)
    assert sage_question(s)=='在超进化大陆霸气有什么用?'
    answer=sage_answer(s)
    assert answer.text=='霸气越高击退敌人的距离越远'
    assert answer.center[1]>200
    original=next(w for w in s.words if w.text==answer.text)
    first=next(w for w in s.words if w.text=='霸气越高越帅')
    original.box[1],first.box[1]=first.box[1],original.box[1]
    moved=sage_answer(s)
    assert moved.text==answer.text and moved.center[1]<150


def test_restart_on_quiz_answers_claims_then_continues_home_once(tmp_path):
    g=SageReplay(tmp_path);g.page='sage-options';g.d.selected=['copies']
    s=g.d.home(g.observe())
    assert is_world(s) and len(g.actions)==3
    assert g.d.report['anomaly_tasks']['sage']['resumed']
    assert g.d.report['sage_quiz']['status']=='done'
    g.d.options['copies']['challenge_copies']=False
    assert '本轮已检查' in g.d.copies() and len(g.actions)==3


@pytest.mark.parametrize('entries,enabled',[
    ([],True),
    ([{'key':'copies','options':{'wandering_sage':False}}],True),
    ([{'key':'copies','options':{'wandering_sage':True}}],True),
    ([{'key':'copies','options':{'wandering_sage':True}}],False),
])
def test_resume_honors_global_trigger_switch_independent_of_task_list(tmp_path,entries,enabled):
    d=daily(tmp_path,{'trigger_events':{'sage_quiz':enabled}});d.planned_entries=entries;d.selected=['main'];seen=[]
    world=captured('v0913-main-world',True)
    d.wandering_sage=lambda **kw:seen.append(kw['entry']) or '已领取'
    d.observe=lambda:world
    initial=captured('v0915-sage-dominance',True)
    if enabled:assert d.resume_sage_dialog(initial) is world
    else:
        with pytest.raises(UserStopped,match='已关闭自动处理'):d.resume_sage_dialog(initial)
    assert len(seen)==int(enabled)


def test_unknown_or_already_submitted_answer_is_not_retried_during_recovery(tmp_path):
    d=daily(tmp_path);d.selected=['copies']
    s=captured('v0915-sage-dominance',True)
    d.wandering_sage=lambda **kw:pytest.fail('Do not resubmit an ambiguous answer')
    for status in ('unknown_answer','answering','incorrect','correct','done'):
        d.report['sage_quiz']={'status':status}
        with pytest.raises(TaskBlocked,match='答题尚未结束'):d.home(s)
