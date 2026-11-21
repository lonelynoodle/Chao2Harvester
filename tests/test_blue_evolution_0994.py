"""Standalone evolution, material exhaustion and exactly-once submission; no game input."""
import json
import cv2
import numpy as np
import pytest

from chao2 import blue_evolution as evolution,star_shop as shop
from chao2.configuration import SPECS,defaults,normalize_settings
from chao2.policy import SafetyStop,TaskBlocked,UserStopped
from chao2.quick_evolution import quick_evolution_enabled,quick_evolution_offer
from chao2.star_supply import blue_monster_info,blue_evolution_unavailable,purple_monster_info,evolution_offer
from test_configuration import daily,screen


def test_new_setting_is_opt_in_independent_and_grouped(tmp_path):
    options=defaults('other')
    assert options['evolve_blue_monsters'] is False
    assert options['blue_evolution_mode']=='count' and options['blue_evolution_count']==1
    fields={f['key']:f for f in SPECS['other']['fields']}
    assert fields['blue_evolution_mode']['enabled_when']=='evolve_blue_monsters'
    assert fields['blue_evolution_count']['enabled_when']=='blue_evolution_mode'
    assert fields['blue_evolution_count']['enabled_value']=='count'
    assert {fields[k]['group'] for k in ('evolve_blue_monsters','blue_evolution_mode','blue_evolution_count')}=={'evolve_blue_monsters'}
    with pytest.raises(SafetyStop,match='未开启'):daily(tmp_path).evolve_blue_monsters()


@pytest.mark.parametrize('option',[
    {'evolve_blue_monsters':'yes'},{'blue_evolution_mode':'forever'},
    {'blue_evolution_count':0},{'blue_evolution_count':-1},
    {'blue_evolution_count':True},{'blue_evolution_count':1.5},
])
def test_bad_options_rejected_before_device_access(option):
    with pytest.raises(ValueError):normalize_settings({'task_options':{'other':option}})


def simulator(tmp_path,monkeypatch,*,blue=10,spores=1000,gold=1000000,count=3,mode='count'):
    d=daily(tmp_path,{'task_options':{'other':{
        'evolve_blue_monsters':True,'blue_evolution_mode':mode,'blue_evolution_count':count,
        'buy_star_spores':False,'convert_star_souls':False,'evolve_blue_for_star_souls':False}}})
    blue_page=screen(('blue',0,0,30,20))
    offer_page=screen(('详细信息',575,25,120,35),('进化',1000,640,50,32))
    purple=screen(('轮脉',720,85,70,32));unknown=screen()
    state={'blue':blue,'spores':spores,'gold':gold,'page':blue_page,'clicks':0,'roster_calls':0}
    def offer(s):
        if s is not offer_page:return None
        return {'name':'轮脉','gold':85000,'spores':45,
                'gold_balance':state['gold'],'spore_balance':state['spores']}
    def next_offer():
        state['roster_calls']+=1
        if not state['blue']:return blue_page,None
        state['page']=offer_page
        return offer_page,offer(offer_page)
    def submit(s,point,anchors,message):
        assert s is offer_page and point==(1025,656)
        journal=json.loads(d.state_file.read_text('utf-8'))[evolution.PENDING]
        assert journal['phase']=='submitted' and journal['spores']==45 and journal['route']=='quick_tree'
        assert state['gold']>=85000 and state['spores']>=45 and state['blue']>0
        state['clicks']+=1;state['gold']-=85000;state['spores']-=45;state['blue']-=1
        state['page']=purple if not state.get('lost_result') else unknown
    d.next_quick_evolution=next_offer
    d.observe=lambda:state['page']
    d.b.click_at=submit;d.b.guard=lambda s:None;d.b.save_screen=lambda *a:None;d.b.sleep=lambda *a:None
    monkeypatch.setattr(evolution,'quick_evolution_offer',lambda b,s:offer(s))
    monkeypatch.setattr(evolution,'quick_evolution_enabled',lambda s:s is offer_page)
    monkeypatch.setattr(evolution,'purple_monster_info',lambda b,s,**kwargs:s is purple)
    monkeypatch.setattr(evolution,'evolution_result_name',lambda *a:None)
    return d,state,purple


def test_exact_count_uses_confirmed_successes_and_retains_purples(tmp_path,monkeypatch):
    d,state,_=simulator(tmp_path,monkeypatch)
    result=d.evolve_blue_monsters()
    assert result['status']=='done' and result['evolved']==state['clicks']==3
    assert result['gold_spent']==255000 and result['spores_spent']==135
    assert state['blue']==7 and result['stop_reason']=='已达到指定进化只数'
    assert len(d.report['blue_evolutions'])==3 and evolution.PENDING not in d.state
    assert not d.options['other']['convert_star_souls']
    assert 'star_conversions' not in d.report and 'star_evolutions' not in d.report
    # The same report/instance is resumable without resetting its quota.
    d.evolve_blue_monsters()
    assert state['clicks']==3


@pytest.mark.parametrize('blue,spores,gold,expected,reason',[
    (2,1000,1000000,2,'蓝怪'),(10,100,1000000,2,'进化孢子不足'),
    (10,1000,170000,2,'金币不足'),(0,1000,1000000,0,'蓝怪'),
    (10,44,1000000,0,'进化孢子不足'),(10,1000,84999,0,'金币不足'),
])
def test_until_empty_stops_at_first_insufficient_resource(tmp_path,monkeypatch,blue,spores,gold,expected,reason):
    d,state,_=simulator(tmp_path,monkeypatch,blue=blue,spores=spores,gold=gold,mode='until_empty',count=1)
    result=d.evolve_blue_monsters()
    assert result['evolved']==state['clicks']==expected and result['requested'] is None
    assert reason in result['stop_reason'] and evolution.PENDING not in d.state


def test_count_can_finish_early_when_stock_exhausted(tmp_path,monkeypatch):
    d,state,_=simulator(tmp_path,monkeypatch,blue=1,count=5)
    result=d.evolve_blue_monsters()
    assert result['evolved']==1 and result['requested']==5 and '蓝怪' in result['stop_reason']


def test_changed_offer_never_submits_or_creates_transaction(tmp_path,monkeypatch):
    d,state,_=simulator(tmp_path,monkeypatch)
    monkeypatch.setattr(evolution,'quick_evolution_offer',lambda *a:None)
    with pytest.raises(TaskBlocked,match='材料余额变化'):d.evolve_blue_monsters()
    assert state['clicks']==0 and evolution.PENDING not in d.state


def test_unseen_result_is_not_counted_or_submitted_twice_on_resume(tmp_path,monkeypatch):
    d,state,_=simulator(tmp_path,monkeypatch);state['lost_result']=True
    with pytest.raises(TaskBlocked,match='未重复进化'):d.evolve_blue_monsters()
    assert state['clicks']==1 and d.blue_evolution_result()['evolved']==0
    assert evolution.PENDING in json.loads(d.state_file.read_text('utf-8'))
    with pytest.raises(TaskBlocked,match='未重复进化'):d.evolve_blue_monsters()
    assert state['clicks']==1 and state['roster_calls']==1


def test_revealed_pending_result_resumes_without_replaying_input(tmp_path,monkeypatch):
    d,state,purple=simulator(tmp_path,monkeypatch,count=1);state['lost_result']=True
    with pytest.raises(TaskBlocked):d.evolve_blue_monsters()
    # Simulate a confirmed reveal followed by its completed purple info screen.
    d.state[evolution.PENDING]['reveal_seen']=True;state['page']=purple
    result=d.evolve_blue_monsters()
    assert result['evolved']==state['clicks']==1 and evolution.PENDING not in d.state


def test_confirmation_is_journaled_and_receipt_is_idempotent(tmp_path,monkeypatch):
    d,state,purple=simulator(tmp_path,monkeypatch,count=1)
    pending={'id':'upgrade-once','name':'轮脉','gold':85000,'spores':45,'phase':'confirmed'}
    d.state[evolution.PENDING]=pending.copy()
    d.complete_blue_evolution(purple)
    d.state[evolution.PENDING]=pending.copy()
    d.complete_blue_evolution(purple)
    assert d.blue_evolution_result()['evolved']==1 and len(d.report['blue_evolutions'])==1
    assert state['clicks']==0 and evolution.PENDING not in d.state


def test_generic_success_reveal_is_closed_before_credit(tmp_path,monkeypatch):
    d,_,purple=simulator(tmp_path,monkeypatch)
    reveal=screen(('进化成功',100,100,120,40),('点击空白位置关闭',450,640,250,40))
    d.state[evolution.PENDING]={'id':'reveal','name':'轮脉','gold':85000,'spores':45,'phase':'submitted'}
    closes=[]
    def close(s,name,**kwargs):
        assert s is reveal and name=='轮脉' and kwargs=={'require_level_one':False}
        assert d.state[evolution.PENDING]['reveal_seen']
        closes.append(True);return purple
    d.close_star_evolution_result=close
    assert d.complete_blue_evolution(reveal) is purple
    assert closes==[True] and d.blue_evolution_result()['evolved']==1


def test_arbitrary_purple_info_cannot_settle_an_old_unseen_transaction(tmp_path,monkeypatch):
    d,_,purple=simulator(tmp_path,monkeypatch)
    d.state[evolution.PENDING]={'id':'unseen','name':'轮脉','gold':85000,'spores':45,'phase':'submitted'}
    with pytest.raises(TaskBlocked,match='未重复进化'):d.complete_blue_evolution(purple)
    assert d.blue_evolution_result()['evolved']==0


def test_stop_during_pending_verification_preserves_transaction(tmp_path,monkeypatch):
    d,_,purple=simulator(tmp_path,monkeypatch)
    d.state[evolution.PENDING]={'id':'stopped','name':'轮脉','phase':'submitted'}
    def stop():raise UserStopped('用户停止')
    d.b.check_stop=stop
    with pytest.raises(UserStopped):d.complete_blue_evolution(purple,submitted_now=True)
    assert evolution.PENDING in d.state and d.blue_evolution_result()['evolved']==0


def test_evolution_quota_is_per_other_task_instance(tmp_path,monkeypatch):
    d,state,_=simulator(tmp_path,monkeypatch,count=1)
    active=['first'];d.report_key=lambda task:active[0]
    first=d.evolve_blue_monsters();active[0]='second'
    second=d.evolve_blue_monsters()
    assert first is not second and first['evolved']==second['evolved']==1
    assert state['clicks']==2


@pytest.mark.parametrize('key',['star_evolution_pending','star_conversion_pending'])
def test_pending_star_operations_do_not_mix_with_standalone_evolution(tmp_path,monkeypatch,key):
    d,state,_=simulator(tmp_path,monkeypatch);d.day[key]={'unconfirmed':True}
    with pytest.raises(TaskBlocked,match='饲星操作尚待核实'):d.evolve_blue_monsters()
    assert state['clicks']==state['roster_calls']==0


def test_star_feeding_does_not_touch_unconfirmed_evolution(tmp_path):
    d=daily(tmp_path,{'task_options':{'other':{
        'buy_star_spores':True,'convert_star_souls':True,'evolve_blue_for_star_souls':True}}})
    d.state[evolution.PENDING]={'id':'pending'}
    with pytest.raises(TaskBlocked,match='尚待核实'):d.convert_one_ultimate(100,0)
    with pytest.raises(TaskBlocked,match='尚待核实'):d.evolve_one_blue_for_star_souls(0)


@pytest.mark.parametrize('predicate,hue',[(blue_monster_info,100),(purple_monster_info,145)])
def test_any_blue_level_is_supported_but_legacy_feeding_still_requires_level_one(tmp_path,predicate,hue):
    d=daily(tmp_path);s=screen(('怪兽信息',100,10,160,30),('进化',1050,420,80,40))
    color=cv2.cvtColor(np.uint8([[[hue,230,230]]]),cv2.COLOR_HSV2BGR)[0,0]
    s.image[78:124,645:710]=color
    reads=[]
    d.b.read_number=lambda *a:reads.append(True) or 50
    assert not predicate(d.b,s)
    assert predicate(d.b,s,require_level_one=False) and reads==[True]
    s.image[78:124,645:710]=0
    assert not predicate(d.b,s,require_level_one=False)


def test_real_material_parser_requires_purple_grade_and_only_gold_spores(tmp_path):
    d=daily(tmp_path)
    s=screen(('进化',110,10,80,30),('轮脉',180,80,80,30),('消耗材料',80,600,120,30),
             ('进化',1020,640,80,35),('608万',1060,10,80,30))
    s.image[70:120,112:170]=cv2.cvtColor(np.uint8([[[145,230,230]]]),cv2.COLOR_HSV2BGR)[0,0]
    s.image[638:670,104:147]=(30,180,220);s.image[639:670,182:218]=(210,210,30)
    d.b.read_number=lambda q,roi:{(98,666,68,28):85000,(207,672,28,23):45,(1220,10,48,35):100}.get(roi)
    assert evolution_offer(d.b,s)=={'name':'轮脉','gold':85000,'spores':45,'gold_balance':6080000,'spore_balance':100}
    forbidden=screen(('极化石',90,605,100,30)).words[0];s.words.append(forbidden)
    assert evolution_offer(d.b,s) is None


def test_other_runs_evolution_after_shop_and_boxes_and_continues_after_failure(tmp_path):
    d=daily(tmp_path);options=d.options['other']
    for field in SPECS['other']['fields']:
        if field['type']=='bool':options[field['key']]=False
    options.update(buy_star_spores=True,open_monster_boxes=True,evolve_blue_monsters=True,clear_bag_notifications=True)
    order=[]
    def job(key):order.append(key);return {'status':'done','message':key}
    d.buy_star_spores=lambda:job('shop');d.open_monster_boxes=lambda:job('boxes')
    def blocked():order.append('evolve');raise TaskBlocked('费用未识别')
    d.evolve_blue_monsters=blocked;d.clear_bag_notifications=lambda:job('bag')
    d.home=lambda:None;d.recover_failed_task=lambda:None
    d.with_page_recovery=lambda run,reason:run()
    with pytest.raises(TaskBlocked,match='部分未完成'):d.other()
    assert order==['shop','boxes','evolve','bag']
    assert d.report['other_tasks']['blue_evolution']['status']=='blocked'


@pytest.mark.parametrize('layout',['unchanged','moved_without_selection','moved_with_selection'])
@pytest.mark.parametrize('unavailable',['locked','cannon','gray'])
def test_roster_skips_unavailable_blue_and_uses_fresh_coordinates_after_list_moves(tmp_path,monkeypatch,layout,unavailable):
    d=daily(tmp_path);roster=screen(('怪兽数量',10,80,120,30),('品质',180,120,80,30))
    info=screen(('怪兽信息',110,10,180,30),('进化',1058,420,56,31))
    rejected=screen(('怪兽信息',110,10,180,30),{
        'locked':('解锁',10,100,60,30),'cannon':('人间大炮',665,90,164,27),'gray':('进化',1058,420,56,31),
    }[unavailable])
    color=cv2.cvtColor(np.uint8([[[100,230,230]]]),cv2.COLOR_HSV2BGR)[0,0]
    for page in (info,rejected):page.image[78:124,645:710]=color
    info.image[420:451,1058:1114]=(230,230,230)
    if unavailable=='gray':rejected.image[424:447,1062:1108]=(93,95,92)
    reopened=screen(('怪兽数量',10,80,120,30),('品质',180,120,80,30))
    if layout!='unchanged':reopened.image[175:675,110:1250]=80
    if layout=='moved_with_selection':
        reopened.image[320,140:210]=255
        reopened.image[344:406,120]=255
    cards=[{'point':(175,250),'level':None},{'point':(300,250),'level':55}]
    shifted_cards=[{'point':(175,375),'level':None},{'point':(300,375),'level':55}]
    def read_cards(s,reader):
        assert reader is None
        return shifted_cards if s is reopened and layout!='unchanged' else cards
    monkeypatch.setattr(shop,'blue_roster_cards',read_cards)
    pages=iter([info,roster,roster,rejected,reopened,roster,info]);selected=[]
    d.observe=lambda:screen();d.territory=lambda:screen();d.b.click_text=lambda *a,**k:None
    d.b.click_at=lambda s,p,*a:selected.append(p) if p in [c['point'] for c in cards+shifted_cards] else None
    def wait(predicate,*a,**k):
        page=next(pages);assert predicate(page);return page
    d.wait_for_screen=wait
    if layout=='moved_without_selection':
        with pytest.raises(TaskBlocked,match='列表位置改变'):d.one_blue_roster(level_one_only=False,skip_locked=True)
        assert selected==[(175,250)]
    else:
        assert d.one_blue_roster(level_one_only=False,skip_locked=True) is info
        assert selected==[(175,250),(300,375 if layout=='moved_with_selection' else 250)]


@pytest.mark.parametrize('bright_button',[False,True])
def test_human_cannon_is_unavailable_even_with_or_without_visible_evolution_text(bright_button):
    s=screen(('怪兽信息',110,10,180,30),('人间大炮',665,90,164,27))
    s.image[78:124,645:710]=cv2.cvtColor(np.uint8([[[100,230,230]]]),cv2.COLOR_HSV2BGR)[0,0]
    if bright_button:
        s.words.extend(screen(('进化',1058,420,56,31)).words)
        s.image[420:451,1058:1114]=230
    assert blue_evolution_unavailable(s)=='人间大炮不可进化'


def test_quick_preview_requires_purple_target_and_blue_material_and_ordinary_costs(tmp_path):
    d=daily(tmp_path)
    s=screen(('详细信息',578,25,123,33),('进化',992,642,65,29),('移动速度',643,370,90,25),
             ('咒刃××',330,489,140,30),('85000',283,675,45,15),('45',410,675,22,16),
             ('610万',1205,33,57,25),('1234',1216,87,46,25))
    def color(hue):
        return cv2.cvtColor(np.uint8([[[hue,230,235]]]),cv2.COLOR_HSV2BGR)[0,0]
    s.image[485:527,180:555]=color(145)
    s.image[624:687,468:532]=color(100)
    s.image[630:673,273:319]=color(25)
    s.image[632:674,376:416]=color(95)
    assert quick_evolution_offer(d.b,s)=={'name':'咒刃','gold':85000,'spores':45,
                                         'gold_balance':6100000,'spore_balance':1234}
    assert not quick_evolution_enabled(s)
    s.image[644:671,995:1052]=255
    assert quick_evolution_enabled(s)
    s.image[624:687,468:532]=color(145)
    assert quick_evolution_offer(d.b,s) is None
