"""Execute the daily/material/refresh planner and team loop against a fake game."""
import re
import time

import pytest

from chao2.configuration import COCOON_CARDS,COCOON_DAILIES,normalize_settings
from chao2.policy import TaskBlocked
from tests.test_configuration import daily,screen


class CocoonGame:
    def __init__(self,tmp_path,monkeypatch,*,spikes=9,books=1,done=(),options=None,fail=(),ignore=(),quotas=None):
        self.clock=0;monkeypatch.setattr(time,'monotonic',lambda:self.clock)
        self.spikes=spikes;self.books=books;self.done=set(done);self.fail=set(fail);self.ignore=set(ignore)
        self.page='menu';self.key=None;self.team=None;self.inputs=[];self.opens=[]
        self.quotas=dict(quotas or {})
        self.d=daily(tmp_path,{'schema_version':5,'task_options':{'cocoon':{
            'daily_tasks':True,'targets':[],'teams':[3,2],**(options or {})}}})
        d=self.d;d.observe=self.observe;d.home=lambda:None
        d.enter_overview=lambda _:self.menu()
        d.b.sleep=lambda seconds:setattr(self,'clock',self.clock+seconds)
        d.b.read_number=lambda s,roi:self.books
        d.b.match_template=self.match;d.b.click_at=self.open;d.b.click_text=self.click
        d.select_team=self.select
        d.exit_result=lambda s:setattr(self,'page','menu')
        d.back_detail=lambda s:self.menu()

    def menu(self):
        self.page='menu';return self.observe()

    def observe(self,*args):
        if self.page=='menu':
            return screen(('永生之茧',124,14,90,24),('刷新',612,496,54,33),
                          (f'{self.spikes}/15',1000,15,45,26),
                          *((k,0,70+i*30,100,20) for i,k in enumerate(sorted(self.done))))
        if self.page=='result':
            return screen(('挑战失败' if self.lost else '胜利',100,200,100,30),
                          ('获得奖励',900,300,100,30),('退出',1140,580,60,30))
        return screen(('敌方阵容',1130,136,100,28),('排阵',824,614,60,35),('挑战',1060,603,61,34),
                      (f'{self.spikes}/15',1210,15,60,26),(f'剩余次数{self.quotas.get(self.key,5)}/5',1025,559,132,23))

    def match(self,s,name,*args):
        if name=='instant-off.png':return True
        return bool(s.find('^lower_'+name.removeprefix('cocoon-daily-done-').removesuffix('.png')+'$'))

    def open(self,s,p,*args):
        self.key=next(k for k,_,point in COCOON_CARDS if point==p);self.opens.append(self.key)
        if self.key not in self.ignore:self.page='detail'

    def select(self,s,team):
        self.team=team;return self.observe()

    def click(self,s,pattern):
        if pattern=='^刷新$':
            assert self.done==set(COCOON_DAILIES) and self.books>0
            self.inputs.append('refresh');self.books-=1;self.done.clear();return
        assert pattern=='^挑战$|^前往挑战$'
        self.inputs.append(self.key);self.spikes-=1
        if self.key in self.quotas:self.quotas[self.key]-=1
        self.lost=self.key in self.fail or (self.key,self.team) in self.fail
        if not self.lost and self.key in COCOON_DAILIES:self.done.add(self.key)
        self.page='result'


def gold(limit=5):return {'id':'gold','label':'富有（金币）','enabled':True,'limit':limit}


def test_all_three_dailies_then_refresh_then_new_dailies_before_materials(tmp_path,monkeypatch):
    g=CocoonGame(tmp_path,monkeypatch,spikes=8,options={'targets':[gold()]})
    g.d.cocoon()
    assert g.inputs==list(COCOON_DAILIES)+['refresh']+list(COCOON_DAILIES)+['gold','gold']
    assert g.books==0 and g.spikes==0 and g.d.report['cocoon_refreshes']==1
    assert all(g.d.report['cocoon_counts'][k]==2 for k in COCOON_DAILIES)


def test_multiple_refreshes_then_materials_until_spikes_used(tmp_path,monkeypatch):
    g=CocoonGame(tmp_path,monkeypatch,spikes=20,books=2,options={'targets':[gold()]})
    g.d.cocoon()
    assert g.inputs==(list(COCOON_DAILIES)+['refresh'])*2+list(COCOON_DAILIES)+['gold']*11
    assert g.spikes==0 and g.d.report['cocoon_refreshes']==2


@pytest.mark.parametrize('spikes,reserve,guard,expected',[(2,0,True,False),(3,0,True,True),(3,1,True,False),(4,1,True,True),(2,0,False,True)])
def test_three_spike_guard_uses_available_balance_and_is_optional(tmp_path,monkeypatch,spikes,reserve,guard,expected):
    g=CocoonGame(tmp_path,monkeypatch,spikes=spikes,done=COCOON_DAILIES,
                options={'reserve_spikes':reserve,'refresh_require_three_spikes':guard})
    g.d.cocoon()
    assert ('refresh' in g.inputs)==expected
    assert g.spikes>=reserve
    if expected:
        assert g.inputs[0]=='refresh'
        assert len(g.inputs)-1==min(3,spikes-reserve)


@pytest.mark.parametrize('option,value',[('refresh_tasks',False),('daily_tasks',False),('max_refreshes',1)])
def test_daily_and_magic_switches_and_refresh_limit_are_respected(tmp_path,monkeypatch,option,value):
    g=CocoonGame(tmp_path,monkeypatch,spikes=20,books=3,done=COCOON_DAILIES,options={option:value})
    g.d.cocoon()
    assert g.inputs.count('refresh')==(1 if option=='max_refreshes' else 0)


def test_failed_daily_can_use_fallback_team_but_never_refreshes_if_all_teams_fail(tmp_path,monkeypatch):
    g=CocoonGame(tmp_path,monkeypatch,fail=[('lower_left',3),'lower_middle'])
    g.d.cocoon()
    assert g.inputs==['lower_left','lower_left','lower_middle','lower_middle','lower_right']
    assert g.books==1 and 'lower_middle' not in g.done
    assert g.d.report['cocoon_failed']==['lower_middle']


def test_missed_card_click_is_not_completion_and_does_not_authorize_refresh(tmp_path,monkeypatch):
    g=CocoonGame(tmp_path,monkeypatch,done=['lower_middle','lower_right'],ignore=['lower_left'])
    with pytest.raises(TaskBlocked,match='该项未记为完成'):g.d.cocoon()
    assert g.opens==['lower_left','lower_left'] and g.inputs==[] and g.books==1


def test_no_books_never_clicks_paid_refresh(tmp_path,monkeypatch):
    g=CocoonGame(tmp_path,monkeypatch,books=0,done=COCOON_DAILIES)
    g.d.cocoon()
    assert g.inputs==[]


def test_dailies_off_only_runs_material_selection(tmp_path,monkeypatch):
    g=CocoonGame(tmp_path,monkeypatch,options={'daily_tasks':False,'targets':[gold(2)]})
    g.d.cocoon()
    assert g.inputs==['gold']*9 and g.spikes==0


def test_refresh_requires_a_second_frame_confirming_all_dailies(tmp_path,monkeypatch):
    g=CocoonGame(tmp_path,monkeypatch,done=COCOON_DAILIES)
    first=g.observe();g.done.remove('lower_left')  # e.g. client daily reset
    assert not g.d.cocoon_refresh(first)
    assert g.inputs==[]


def test_removed_run_limit_does_not_block_refresh(tmp_path,monkeypatch):
    g=CocoonGame(tmp_path,monkeypatch,done=COCOON_DAILIES,options={'max_runs':2})
    g.d.cocoon()
    assert g.inputs==['refresh',*COCOON_DAILIES] and g.books==0


def test_legacy_partial_daily_selection_becomes_one_checkbox_and_material_rows_keep_order():
    old={'schema_version':4,'task_options':{'cocoon':{'targets':[
        {'id':'spore','enabled':True,'limit':2},{'id':'lower_right','enabled':True,'limit':1},gold(3)]}}}
    updated=normalize_settings(old)['task_options']['cocoon']
    assert updated['daily_tasks'] is True
    assert [r['id'] for r in updated['targets']]==['spore','gold']
    assert all('limit' not in r for r in updated['targets'])
    assert normalize_settings({'schema_version':4,'task_options':{'cocoon':{'targets':[]}}})['task_options']['cocoon']['daily_tasks'] is False


def test_actual_client_quota_exhaustion_moves_to_next_material(tmp_path,monkeypatch):
    g=CocoonGame(tmp_path,monkeypatch,spikes=8,quotas={'gold':2},options={
        'daily_tasks':False,'targets':[gold(1),{'id':'spore','enabled':True,'limit':1}]})
    g.d.cocoon()
    assert g.inputs==['gold']*2+['spore']*6 and g.spikes==0


@pytest.mark.parametrize('enabled,remaining',[(False,0),(True,3)])
def test_reserve_checkbox_controls_effective_balance(tmp_path,monkeypatch,enabled,remaining):
    g=CocoonGame(tmp_path,monkeypatch,spikes=8,options={
        'daily_tasks':False,'targets':[gold()],'reserve_spikes':3,'reserve_spikes_enabled':enabled})
    g.d.cocoon()
    assert g.spikes==remaining and len(g.inputs)==8-remaining


def test_reentry_keeps_failed_material_and_attempt_ledger(tmp_path,monkeypatch):
    g=CocoonGame(tmp_path,monkeypatch,spikes=10,options={
        'daily_tasks':False,'targets':[gold()]},fail=['gold'])
    g.d.cocoon()
    assert g.inputs==['gold','gold'] and g.d.report['cocoon_failed']==['gold']
    g.d.cocoon()
    assert g.inputs==['gold','gold'] and g.d.report['cocoon_counts']['gold']==2
