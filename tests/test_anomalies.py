"""Captured failure/quiz replay; no emulator or live input."""
import pytest
from chao2.anomalies import (is_sage_offer,is_sage_dialog,evolved_copy_without_instant,
                            instant_checkbox_present,instant_frame,sage_question,sage_choices,
                            sage_answer,sage_verdict)
from chao2.backend import Word
from chao2.workflows import is_world,TASKS
from chao2.configuration import normalize_settings,SPECS
from chao2.activities import BudgetReached
from chao2.policy import TaskBlocked,SafetyStop
from test_configuration import captured,daily


def test_evolved_layout_without_instant_is_distinct_from_normal_or_checked(tmp_path):
    s=captured('v088-copy-evolved',True)
    assert evolved_copy_without_instant(s)
    d=daily(tmp_path);d.b.match_template=lambda q,name,*args:name=='copy-own-exp50.png'
    d.verify_instant_setting('copies',s)
    template,_=instant_frame();s.image[685:685+template.shape[0],1010:1010+template.shape[1]]=template
    # Checked center cannot disappear from the rim detection.
    s.image[695:704,1020:1029]=255
    assert instant_checkbox_present(s) and not evolved_copy_without_instant(s)
    with pytest.raises(TaskBlocked,match='瞬破'):d.verify_instant_setting('copies',s)
    s=captured('v088-copy-evolved',True)
    for w in s.words:
        if '暴进' in w.text:w.text='普通复制体'
    assert not evolved_copy_without_instant(s)
    d.observe=lambda:s;d.b.guard=lambda *_:None;d.b.sleep=lambda *_:None
    with pytest.raises(TaskBlocked,match='瞬破'):d.verify_instant_setting('copies',s)


def test_evolved_copy_animation_frame_is_rechecked_before_instant_failure(tmp_path):
    s=captured('v088-copy-evolved',True)
    partial=captured('v088-copy-evolved',True)
    partial.words=[w for w in partial.words if w.text!='排阵']
    assert not evolved_copy_without_instant(partial)
    d=daily(tmp_path);reads=[]
    d.b.match_template=lambda q,name,*args:name=='copy-own-exp50.png'
    d.b.sleep=lambda *_:None
    d.b.guard=lambda *_:None
    d.observe=lambda:reads.append('read') or s
    d.verify_instant_setting('copies',partial)
    assert reads==['read']


def test_world_with_short_task_anchor_but_not_sage_overlays():
    assert is_world(captured('v088-world-short-task',True))
    for name in ('sage-detail','sage-arrived','sage-options','sage-answer-result','sage-after-correct','anomaly-list'):
        assert not is_world(captured('v088-'+name,True))
    s=captured('v088-world-short-task',True)
    s.words=[w for w in s.words if w.text!='世界回响']
    assert not is_world(s)  # One isolated challenge label is insufficient.


def test_actual_question_unique_answer_and_unknown_not_guessed():
    assert is_sage_offer(captured('v088-sage-detail'))
    s=captured('v088-sage-options')
    assert is_sage_dialog(s) and sage_question(s)=='部落一个赛季通常会持续多久?'
    assert len(sage_choices(s))==3 and sage_answer(s).text=='一个月'
    assert sage_verdict(captured('v088-sage-answer-result'))=='correct'
    assert sage_answer(s,[]) is None
    s.words.append(Word('一个月',[829,395,84,33],.99))
    assert sage_answer(s) is None  # Never select one of two equally matching options.


def test_configuration_retains_copy_options_and_exposes_independent_children():
    old={'tasks':['copies'],'stamina_order':['hunt','copies','main'],
         'task_options':{'copies':{'teams':[3,1],'max_runs':4,'include_friends':True}}}
    out=normalize_settings(old)
    assert TASKS['copies'][0]=='异象'
    assert out['tasks']==old['tasks'] and out['stamina_order']==old['stamina_order']
    for key,value in old['task_options']['copies'].items():assert out['task_options']['copies'][key]==value
    assert out['task_options']['copies']['challenge_copies'] and out['task_options']['copies']['wandering_sage']
    fields={f['key']:f for f in SPECS['copies']['fields']}
    assert all(fields[k]['enabled_when']=='challenge_copies' for k in ('teams','max_runs','include_friends'))
    assert 'enabled_when' not in fields['wandering_sage']


@pytest.mark.parametrize('error',[BudgetReached('达到战斗上限'),TaskBlocked('瞬破未确认关闭')])
def test_sage_still_runs_after_copy_limit_or_failure(tmp_path,error):
    d=daily(tmp_path);seen=[]
    def copies():seen.append('copies');raise error
    d.copy_battles=copies
    d.wandering_sage=lambda:seen.append('sage') or '智者已领奖'
    if type(error) is TaskBlocked:
        with pytest.raises(TaskBlocked,match='复制体'):d.copies()
    else:assert '智者已领奖' in d.copies()
    assert seen==['copies','sage']
    assert d.report['anomaly_tasks']['sage']['status']=='done'


def test_no_sage_recheck_during_free_stamina_continuation(tmp_path):
    d=daily(tmp_path);seen=[]
    d.copy_battles=lambda:seen.append('copy') or '复制体通关'
    d.wandering_sage=lambda:seen.append('sage') or '暂无智者'
    d.copies();d.copies()
    assert seen==['copy','sage','copy']


def test_only_sage_does_not_refill_stamina_or_inspect_copies(tmp_path):
    d=daily(tmp_path,{'task_options':{'copies':{'challenge_copies':False}}})
    d.selected=['copies'];d.wandering_sage=lambda:'智者已检查'
    d.copy_battles=lambda:pytest.fail('disabled child')
    assert d.copies()=='智者已检查'
    assert d.stamina_retry['copies'] is False
    assert '没有勾选使用体力的玩法' in d.replenish_stamina()
    assert d.stamina_outlet_available(['copies'],0) is False


def test_safety_stop_cannot_be_swallowed_to_start_next_child(tmp_path):
    d=daily(tmp_path)
    def fail():raise SafetyStop('付费弹窗')
    d.copy_battles=fail;d.wandering_sage=lambda:pytest.fail('unsafe continuation')
    with pytest.raises(SafetyStop):d.copies()


class SageReplay:
    def __init__(self,tmp_path):
        self.d=daily(tmp_path);self.page='sage-reward-closed';self.actions=[]
        self.d.b.sleep=lambda _:None
        self.d.observe=self.observe
        self.d.copy_list=self.copy_list;self.d.copy_first_page=lambda s:s
        self.d.b.click_at=self.click;self.d.b.click_text=self.click_text
    def observe(self,*args):return captured('v088-'+self.page,True)
    def copy_list(self):self.page='anomaly-list';return self.observe()
    def click_text(self,s,pattern,roi=None):
        w=s.find(pattern,roi);assert w
        self.click(s,w.center,[pattern],'前往')
    def click(self,s,point,anchors,reason):
        assert s.has(*anchors)
        self.actions.append((self.page,reason))
        self.page={'anomaly-list':'sage-detail','sage-detail':'sage-arrived','sage-arrived':'sage-options',
                   'sage-options':'sage-answer-result','sage-answer-result':'sage-after-correct',
                   'sage-after-correct':'sage-reward-closed'}[self.page]


def test_captured_sage_sequence_to_actual_reward_and_world(tmp_path):
    g=SageReplay(tmp_path)
    assert '奖励已领取' in g.d.wandering_sage()
    assert [x[0] for x in g.actions]==['anomaly-list','sage-detail','sage-arrived','sage-options','sage-answer-result','sage-after-correct']
    assert g.d.report['sage_quiz']['status']=='done'
    assert g.d.report['sage_quiz']['reward_observed']
    assert g.d.battles==0 and 'resource_usage' not in g.d.report


def test_unknown_question_saved_without_answer_click(tmp_path):
    g=SageReplay(tmp_path);g.page='sage-options'
    g.d.options['copies']['sage_until_end']=False
    observe=g.d.observe
    def unknown(*args):
        s=observe()
        for w in s.words:
            if '部落一个赛季' in w.text:w.text='尚未校准的题目？'
        return s
    g.d.observe=unknown
    with pytest.raises(TaskBlocked,match='尚未收录'):g.d.wandering_sage()
    assert g.actions==[] and (tmp_path/'sage-question.json').exists()
    assert g.d.report['sage_quiz']['status']=='unknown_answer'


def test_preexisting_correct_result_resumes_claim_without_reanswer(tmp_path):
    g=SageReplay(tmp_path);g.page='sage-answer-result'
    assert '奖励已领取' in g.d.wandering_sage()
    assert [x[0] for x in g.actions]==['sage-answer-result','sage-after-correct']


def test_no_reward_after_correct_answer_is_not_claimed(tmp_path):
    g=SageReplay(tmp_path);g.page='sage-answer-result'
    g.d.options['copies']['sage_until_end']=False
    def timeout(*args,**kwargs):raise TaskBlocked('奖励尚未出现')
    g.d.sage_wait=timeout
    with pytest.raises(TaskBlocked,match='奖励尚未出现'):g.d.wandering_sage()
    assert not g.d.report['sage_quiz'].get('reward_observed')
    assert len(g.actions)==1


def test_sage_missing_only_skips_its_child(tmp_path):
    g=SageReplay(tmp_path)
    def missing():
        s=captured('v088-anomaly-list',True);s.words=[w for w in s.words if w.text!='游荡智者'];return s
    g.d.copy_list=missing;g.d.home=lambda:None
    assert '没有游荡智者' in g.d.wandering_sage() and not g.actions
