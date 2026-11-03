"""Replay the interrupted tower entrance and unbanked sage question from 00:11."""
import copy
import pytest

from chao2.anomalies import sage_choices,sage_phase,sage_answer
from chao2.configuration import normalize_settings,SPECS
from chao2.policy import TaskBlocked,SafetyStop,UserStopped
from test_configuration import daily,screen,captured
from test_anomalies import SageReplay
from test_navigation_retry import clocked


def test_tower_recovers_entrance_consumed_by_gift(tmp_path,monkeypatch):
    d=daily(tmp_path);clocked(d,monkeypatch)
    territory=captured('v0924-tower-territory',True)
    selector=screen(('选择挑战的塔',450,80,350,45),('无限制',280,300,80,30))
    tower=captured('tower-map');clicks=[]
    def observe():
        if len(clicks)<2:return territory  # Gift was closed onto territory.
        return selector if len(clicks)==2 else tower
    def click(s,point,anchors,reason):
        assert d.tower_territory(s) and s.has(*anchors)
        clicks.append(reason)
    d.observe=observe;d.b.click_at=click
    d.b.click_text=lambda s,pattern:clicks.append('select') if s.find(pattern) else pytest.fail('wrong selection')
    d.territory=lambda:pytest.fail('Already on territory; no world/overview round trip')
    assert d.open_tower({'id':'normal','label':'无限制'}) is tower
    assert clicks==['进入浮空巨塔','进入浮空巨塔','select']
    assert len(d.report['navigation_retries'])==1


@pytest.mark.parametrize('unknown',[False,True])
def test_tower_retry_is_bounded_and_never_clicks_unknown_page(tmp_path,monkeypatch,unknown):
    d=daily(tmp_path);clock=clocked(d,monkeypatch)
    territory=captured('v0924-tower-territory');clicks=[]
    def observe():
        territory.when=clock[0]
        return screen() if unknown else territory
    d.observe=observe
    d.b.click_at=lambda *args:clicks.append(args)
    with pytest.raises(TaskBlocked,match='已重试3次'):d.enter_tower_selector(territory)
    assert len(clicks)==(1 if unknown else 4)


def test_actual_question_has_three_buttons_not_four_and_default_is_continuous():
    s=captured('v0924-sage-question',True)
    choices=sage_choices(s)
    assert len(choices)==3 and choices[1].text=='将策划饲星选我!答错误奖励也一样'
    assert sage_answer(s) is None
    cfg=normalize_settings({'task_options':{'copies':{'teams':[2],'wandering_sage':False}}})
    assert cfg['task_options']['copies']['sage_until_end'] is True
    field=next(f for f in SPECS['copies']['fields'] if f['key']=='sage_until_end')
    assert field['enabled_when']=='wandering_sage'
    cfg['task_options']['copies']['sage_until_end']=False
    assert normalize_settings(cfg)['task_options']['copies']['sage_until_end'] is False


def test_result_with_old_choices_is_not_another_question():
    s=captured('v088-sage-answer-result')
    assert sage_choices(s) and sage_phase(s)[0]=='verdict'


class ContinuousSage:
    def __init__(self,tmp_path,monkeypatch,wrong=True,more_dialog=True):
        self.d=daily(tmp_path);self.clock=clocked(self.d,monkeypatch)
        question=captured('v0924-sage-question',True)
        result=captured('v088-sage-answer-result',True)
        for w in result.words:
            if '部落一个赛季' in w.text:w.text='无法战胜敌人时怎么办?'
            if wrong and '答对了' in w.text:w.text='（可惜，答错了！）'
        extra=captured('v088-sage-arrived',True)
        for w in extra.words:
            if '部落一个赛季' in w.text:w.text='今天的问答结束了，明天再见。'
        self.frames=[question,result,captured('v088-sage-after-correct',True)]
        if more_dialog:self.frames.append(extra)
        self.frames.append(captured('v088-sage-reward-closed',True))
        self.index=0;self.actions=[];self.hold=0
        self.d.observe=self.observe;self.d.b.click_at=self.click
    def observe(self,*args):
        s=copy.deepcopy(self.frames[self.index]);s.when=self.clock[0]
        return s
    def click(self,s,point,anchors,reason):
        assert s.has(*anchors)
        self.actions.append(reason)
        if self.hold:self.hold-=1
        else:self.index+=1


def test_unknown_question_wrong_answer_and_post_reward_dialog_all_complete(tmp_path,monkeypatch):
    g=ContinuousSage(tmp_path,monkeypatch)
    assert '奖励已领取' in g.d.wandering_sage(entry=g.observe())
    row=g.d.report['sage_quiz']
    assert row['status']=='done' and row['rewards_closed']==1
    assert row['answers'][0]['source']=='持续完成'
    assert row['answers'][0]['answer'].startswith('将策划饲星')
    assert row['verdicts']==['incorrect'] and len(g.actions)==4
    assert g.d.battles==0 and not g.d.report.get('resource_usage')


def test_stuck_submitted_answer_is_not_repeated(tmp_path,monkeypatch):
    g=ContinuousSage(tmp_path,monkeypatch);g.hold=1
    with pytest.raises(TaskBlocked,match='未重复选择'):g.d.wandering_sage(entry=g.observe())
    assert g.actions==['回答游荡智者']
    assert g.d.report['sage_quiz']['pending_answer']
    # Reentering the same in-memory encounter still cannot resubmit.
    with pytest.raises(TaskBlocked,match='未重复选择'):g.d.wandering_sage(entry=g.observe())
    assert g.actions==['回答游荡智者']


def test_dialog_advance_retries_three_times_then_stops(tmp_path,monkeypatch):
    g=ContinuousSage(tmp_path,monkeypatch);g.index=1;g.hold=10
    with pytest.raises(TaskBlocked,match='已重试3次'):g.d.wandering_sage(entry=g.observe())
    assert g.actions==['继续智者对话']*4
    assert not g.d.report['sage_quiz'].get('reward_observed')


def test_multiple_questions_continue_until_world(tmp_path,monkeypatch):
    g=ContinuousSage(tmp_path,monkeypatch,wrong=False,more_dialog=False)
    q=captured('v0915-sage-dominance',True)
    result=copy.deepcopy(g.frames[1])
    for w in result.words:
        if '无法战胜' in w.text:w.text='在超进化大陆霸气有什么用?'
    g.frames[2:2]=[q,result]
    assert '奖励已领取' in g.d.wandering_sage(entry=g.observe())
    row=g.d.report['sage_quiz']
    assert len(row['answers'])==2 and row['answers'][1]['source']=='题库'
    assert row['status']=='done'


@pytest.mark.parametrize('error',[SafetyStop('付费弹窗'),UserStopped('停止')])
def test_continuous_sage_respects_stop_and_cost_guard(tmp_path,monkeypatch,error):
    g=ContinuousSage(tmp_path,monkeypatch)
    def stop(s):raise error
    g.d.b.guard=stop
    with pytest.raises(type(error)):g.d.wandering_sage(entry=g.observe())
    assert g.actions==[] and not g.d.report.get('sage_quiz')


def test_unexpected_world_return_does_not_invent_reward(tmp_path,monkeypatch):
    g=ContinuousSage(tmp_path,monkeypatch);g.frames=g.frames[:1]+g.frames[-1:]
    with pytest.raises(TaskBlocked,match='未观察到奖励'):g.d.wandering_sage(entry=g.observe())
    assert g.d.report['sage_quiz']['status']=='ended_without_reward'
