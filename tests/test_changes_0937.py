"""Replay swallowed tower clicks and the previously unknown sleepy merchant."""
import pytest

from chao2.merchant import merchant_action,merchant_choice,merchant_choices
from chao2.merchant_settings import MERCHANT_SPEC,merchant_options
from chao2.policy import TaskBlocked,SafetyStop
from test_configuration import captured,daily,screen
from test_merchant_event import setup,world,page
from test_tower_flow import KINDS,TowerGame


def tower_next(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None;clicks=[]
    old=captured('v0937-tower-400-result',True)
    d.b.click_text=lambda *args,**kw:clicks.append(args)
    return d,old,clicks


def test_swallowed_next_click_retries_then_keeps_floor_chain_and_secret_scope(tmp_path):
    game=TowerGame(tmp_path,balance=4);original=game.d.b.click_text;drops=[0]
    def click(s,pattern,**kwargs):
        if '下一' in pattern and drops[0]<1:
            drops[0]+=1;return
        return original(s,pattern,**kwargs)
    game.d.b.click_text=click
    game.d.tower()
    assert len(game.challenges)==4 and game.balance==0
    assert game.secrets==['normal','dragon','puppet'] and game.opened==['normal']
    assert game.next_clicks==3 and game.d.report['tower_next_clicks']==4
    assert len(game.d.report['navigation_retries'])==1


def test_late_combat_seen_before_retry_does_not_send_second_click(tmp_path):
    d,old,clicks=tower_next(tmp_path)
    combat=screen(('自动',100,30,60,30))
    frames=iter([old]*8+[combat]);d.observe=lambda:next(frames)
    result,started=d.tower_advance(old,KINDS[0],401)
    assert result is combat and started and len(clicks)==1
    assert not d.report.get('navigation_retries')


def test_fast_following_victory_is_not_clicked_as_if_it_were_previous_result(tmp_path):
    d,old,clicks=tower_next(tmp_path)
    newer=captured('v0937-tower-400-result')
    for w in newer.words:
        if w.text=='4/20':w.text='3/20'
    d.observe=lambda:newer
    result,started=d.tower_advance(old,KINDS[0],401)
    assert result is newer and started and len(clicks)==1


@pytest.mark.parametrize('balance',['missing','changed'])
def test_unreadable_or_unexpected_feather_balance_prevents_retry(tmp_path,balance):
    d,old,clicks=tower_next(tmp_path)
    unclear=captured('v0937-tower-400-result')
    if balance=='missing':unclear.words=[w for w in unclear.words if w.text!='4/20']
    else:
        for w in unclear.words:
            if w.text=='4/20':w.text='2/20'
    d.observe=lambda:unclear
    with pytest.raises(TaskBlocked,match='未重复点击'):d.tower_advance(old,KINDS[0],401)
    assert len(clicks)==1


def test_random_merchant_mode_is_a_separate_choice_without_purchase_options():
    assert merchant_options({'merchant_options':{'mode':'random'}})['mode']=='random'
    fields={f['key']:f for f in MERCHANT_SPEC['fields']}
    assert 'random' in {r['id'] for r in fields['mode']['choices']}
    assert fields['items']['enabled_value']==fields['diamond_budget']['enabled_value']=='buy'
    assert merchant_options({})['mode']=='skip'


@pytest.mark.parametrize('index',[0,1,2])
def test_all_three_actual_sleepy_merchant_choices_work_in_random_mode(tmp_path,monkeypatch,index):
    d,_=setup(tmp_path);s=captured('v0937-merchant-sleepy',True)
    monkeypatch.setattr('chao2.merchant.random.choice',lambda rows:rows[index])
    chosen=merchant_choices(s)[index]
    action=merchant_action(d.b,s,'random',{})
    assert action[0]=='choice:'+chosen.text and action[1]==chosen.center
    assert '随机选择' in action[3]
    assert merchant_action(d.b,s,'skip') is None


def test_random_selection_is_kept_for_all_reads_and_click_retries(tmp_path,monkeypatch):
    d,clicks=setup(tmp_path);d.b.settings['merchant_options']['mode']='random'
    s=captured('v0937-merchant-sleepy',True);choices=[]
    def choose(rows):choices.append(rows);return rows[-1]
    monkeypatch.setattr('chao2.merchant.random.choice',choose)
    d.observe=lambda:s
    with pytest.raises(SafetyStop,match='已重试3次'):d.handle_merchant(s)
    assert len(choices)==1 and len(clicks)==4
    assert {reason for _,reason in clicks}=={'神秘商人随机选择：了解它困的原因'}
    row=d.report['merchant_events'][0]
    assert row['mode']=='random' and row['purchases']==0


def test_sleepy_merchant_finishes_and_returns_without_counting_a_copy_win(tmp_path,monkeypatch):
    d,clicks=setup(tmp_path);d.b.settings['merchant_options']['mode']='random'
    selected=captured('v0937-merchant-sleepy',True)
    farewell=captured('v0937-merchant-sleepy',True)
    farewell.words=[w for w in farewell.words if w.text!='请选择' and w not in merchant_choices(farewell)]
    for w in farewell.words:
        if w.text=='好困啊，好想睡觉':w.text='下次见'
    state=[selected]
    def click(s,point,anchors,reason):
        assert s.has(*anchors);clicks.append((point,reason))
        state[0]=farewell if '随机选择' in reason else world()
    monkeypatch.setattr('chao2.merchant.random.choice',lambda rows:rows[0])
    d.b.click_at=click;d.observe=lambda:state[0]
    returned=d.handle_merchant(selected)
    assert returned.has('事件','领地')
    assert len(clicks)==2 and d.report['merchant_events'][0]['status']=='completed'
    assert d.battles==0 and not d.task_counts and d.active_task=='copies'


def test_random_mode_leaves_shop_even_with_purchase_items_selected(tmp_path):
    d,_=setup(tmp_path)
    s=page('shop');action=merchant_action(d.b,s,'random',{})
    assert action[0]=='shop' and action[1]==s.find('^离开$').center


def test_random_does_not_select_explicit_purchase_or_resource_spending(monkeypatch):
    s=captured('v0937-merchant-sleepy')
    for w,text in zip(merchant_choices(s),('花费25钻石','购买极化石','支付100钻石')):w.text=text
    monkeypatch.setattr('chao2.merchant.random.choice',lambda _:pytest.fail('No paid choices'))
    assert merchant_choice(s,'random',{}) is None


def test_random_waits_for_choice_header_and_confident_options(tmp_path):
    d,_=setup(tmp_path);s=captured('v0937-merchant-sleepy')
    for w in merchant_choices(s):w.score=.6
    assert merchant_action(d.b,s,'random',{}) is None
    s=captured('v0937-merchant-sleepy');s.words=[w for w in s.words if w.text!='请选择']
    assert merchant_action(d.b,s,'random',{}) is None
