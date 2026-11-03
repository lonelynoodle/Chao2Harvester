"""Exercise list navigation without a device, including real recorded OCR data."""
import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from chao2.backend import Backend, Screen, Word
from chao2.activities import copy_fingerprint, copy_rows, is_copy_list
from chao2.workflows import Daily, is_world


def screen(words):
    return Screen(np.zeros((720,1280,3),np.uint8),
                  [Word(text,[x,y,w,h],.99) for text,x,y,w,h in words],time.monotonic())


class Game:
    def __init__(self,tmp_path,monkeypatch,pages,*,on_list=True,quota=449,loading=False):
        self.clock=0;self.page=0;self.pages=pages;self.quota=quota
        self.on_list=on_list;self.detail=None;self.loading=loading;self.blanks=0
        self.entries=0;self.opens=[];self.swipes=[];self.on_return=lambda:None
        monkeypatch.setattr(time,'monotonic',lambda:self.clock)
        self.b=Backend({},log=lambda _:None)
        self.d=Daily(self.b,{'folder':tmp_path,'events':[]})
        self.d.options['copies']['include_friends']=True
        self.d.observe=self.observe;self.d.enter_overview=self.enter
        self.d.open_anomaly_list=lambda s:self.enter('^异象$')
        self.d.home=lambda *a,**kw:pytest.fail('List scan must not navigate home')
        self.b.sleep=lambda seconds:setattr(self,'clock',self.clock+seconds)
        self.b.controller=SimpleNamespace(post_swipe=self.swipe)
        self.b.wait=lambda job:job;self.b.click_at=self.click
        self.b.match_template=lambda s,name,*a: (name=='copy-own-exp50.png') == (self.kind(s)=='own')
        self.b.read_number=lambda *a:20

    def kind(self,s):
        identity=s.region_text((125,125,390,40))
        return next(kind for page in self.pages for name,kind in page if name==identity)

    def observe(self,*args):
        if self.blanks:
            self.blanks-=1;return screen([])
        if self.detail:
            return screen([('敌方阵容',1100,120,120,30),('排阵',830,610,80,30),
                           ('挑战',1060,605,80,30),(self.detail,140,135,180,25)])
        if not self.on_list:return screen([])
        words=[('异象',974,23,56,31),(f'本周已获取友好点数{self.quota}',892,80,240,19)]
        for i,(name,_) in enumerate(self.pages[self.page]):
            y=269+i*142
            words.extend([(name+f'00:46:{int(self.clock)%60:02d}',914,y-54,240,23),('20',1060,y-10,28,21)])
        return screen(words)

    def enter(self,pattern):
        assert pattern=='^异象$'
        self.entries+=1;self.on_list=True;self.page=0
        return self.observe()

    def swipe(self,x,start,xx,end,duration):
        assert self.on_list and self.detail is None
        self.swipes.append('up' if start<end else 'down')
        self.page=max(0,min(len(self.pages)-1,self.page+(-1 if start<end else 1)))
        return SimpleNamespace(succeeded=True)

    def click(self,s,point,anchors,reason):
        self.b.guard(s);assert s.has(*anchors)
        if reason in ('检查复制体奖励','重试打开同一复制体'):
            rows=copy_rows(s);index=min(range(len(rows)),key=lambda i:abs(rows[i]-35-point[1]))
            self.detail=self.pages[self.page][index][0];self.opens.append(self.detail)
        elif reason=='返回玩法':
            self.detail=None;self.on_return()
            if self.loading:self.blanks=2
        else:pytest.fail('Unexpected navigation: '+reason)
        self.b.sleep(2)


def test_reuses_existing_list_without_reopening_world_or_overview(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('own','own')]])
    assert g.d.copy_targets('own',set())['identity']=='own'
    assert g.entries==0 and g.opens==['own'] and g.swipes==[]


def test_single_entry_scans_rows_and_waits_for_closing_animation(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('friend','friend'),('own','own')]],on_list=False,loading=True)
    assert g.d.copy_targets('own',set())['identity']=='own'
    assert g.entries==1 and g.opens==['friend','own'] and g.swipes==[]


def test_scrolls_once_to_next_page_and_rewinds_inside_list_for_next_scan(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('friend','friend')],[('own','own')]])
    found=g.d.copy_targets('own',set())
    assert found['identity']=='own' and found['page']==1
    assert g.swipes==['down']
    g.d.back_detail(found['screen'])
    assert g.d.copy_targets('friend',set())['identity']=='friend'
    assert g.entries==0 and g.swipes==['down','up']


def test_no_own_targets_keeps_list_open_for_friend_phase(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('friend','friend')]],on_list=False)
    assert g.d.copy_targets('own',set()) is None
    assert g.d.copy_targets('friend',set())['identity']=='friend'
    assert g.entries==1 and g.opens==['friend','friend']
    assert g.swipes==['down','up']


def test_friend_cap_stops_without_opening_targets_but_still_allows_own(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('own','own')]],quota=1000)
    assert g.d.copy_targets('friend',set()) is None
    assert g.opens==[]
    assert g.d.copy_targets('own',set())['kind']=='own'


def test_excluded_failed_target_does_not_hide_later_targets(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('failed','own'),('next','own')]])
    assert g.d.copy_targets('own',{'failed'})['identity']=='next'
    assert g.opens==['failed','next'] and g.entries==0


def test_expired_row_rescans_fresh_positions_without_reentering(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('expiring','friend'),('own','own')]])
    def expire():
        if len(g.pages[0])==2:g.pages[0].pop(0)
    g.on_return=expire
    assert g.d.copy_targets('own',set())['identity']=='own'
    assert g.entries==0 and g.opens==['expiring','own']


def test_recorded_event_list_is_not_world_and_timer_does_not_change_page():
    from private_capture import capture_file
    words=[Word(**w) for w in json.loads(capture_file('copy-list.json').read_text('utf-8'))]
    s=Screen(np.zeros((720,1280,3),np.uint8),words,time.monotonic())
    assert is_copy_list(s) and not is_world(s)
    assert copy_rows(s)==[269,411,552]
    before=copy_fingerprint(s)
    for w in words:w.text=w.text.replace('46:38','45:01')
    assert copy_fingerprint(s)==before


def test_copy_scan_stops_on_user_cancel_before_any_input(tmp_path,monkeypatch):
    from chao2.policy import UserStopped
    g=Game(tmp_path,monkeypatch,[[('own','own')]])
    g.b.stop.set()
    with pytest.raises(UserStopped):g.d.copy_targets('own',set())
    assert g.opens==[] and g.entries==0 and g.swipes==[]

def test_failed_swipe_does_not_count_as_end_of_target_list(tmp_path,monkeypatch):
    from chao2.policy import TaskBlocked
    g=Game(tmp_path,monkeypatch,[[('friend','friend')]])
    g.b.controller.post_swipe=lambda *a:SimpleNamespace(succeeded=False)
    with pytest.raises(TaskBlocked,match='翻页未成功'):g.d.copy_targets('own',set())


def test_ignored_open_during_banner_retries_same_target_without_world_navigation(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('own','own')]])
    click=g.click;calls=[]
    def ignore_first(s,p,anchors,reason):
        calls.append(reason)
        if len(calls)==1:
            g.blanks=2;g.b.sleep(2);return
        click(s,p,anchors,reason)
    g.b.click_at=ignore_first
    assert g.d.copy_targets('own',set())['identity']=='own'
    assert calls==['检查复制体奖励','重试打开同一复制体'] and g.entries==0


def test_target_expires_after_click_rescans_instead_of_retrying_old_coordinates(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('expired','own'),('next','own')]])
    click=g.click;first=[True]
    def expire(s,p,anchors,reason):
        if first.pop() if first else False:
            g.pages[0].pop(0);return
        click(s,p,anchors,reason)
    g.b.click_at=expire
    assert g.d.copy_targets('own',set())['identity']=='next'
    assert g.opens==['next'] and g.entries==0


def test_repeated_ignored_click_is_bounded_and_does_not_guess_another_target(tmp_path,monkeypatch):
    from chao2.policy import TaskBlocked
    g=Game(tmp_path,monkeypatch,[[('own','own')]])
    clicks=[];g.b.click_at=lambda s,p,anchors,reason:clicks.append(p)
    with pytest.raises(TaskBlocked,match='重试后仍未打开'):g.d.copy_targets('own',set())
    assert len(clicks)==3 and len(set(clicks))==1 and g.entries==0


def test_detail_return_resetting_list_to_top_does_not_repeat_first_page(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('friend1','friend')],[('friend2','friend'),('own','own')]])
    g.on_return=lambda:setattr(g,'page',0)
    assert g.d.copy_targets('own',set())['identity']=='own'
    assert g.opens==['friend1','friend2','own'] and g.entries==0


def test_ocr_variation_in_another_row_does_not_restart_entire_scan(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('friend1','friend'),('friend2','friend'),('own','own')]])
    original=g.observe
    def observe(*args):
        s=original(*args)
        if not g.detail:
            for w in s.words:
                if w.text.startswith('friend2') and len(g.opens)%2:w.text=w.text.replace('friend2','frlend2')
        return s
    g.d.observe=observe
    assert g.d.copy_targets('own',set())['identity']=='own'
    assert g.opens==['friend1','friend2','own'] and g.entries==0


def test_timer_removal_preserves_digits_at_end_of_player_name(tmp_path,monkeypatch):
    g=Game(tmp_path,monkeypatch,[[('玩家1','friend'),('玩家2','own')]])
    assert copy_fingerprint(g.observe())==('玩家1','玩家2')


def test_partly_hidden_row_cannot_click_fixed_resonance_banner():
    s=screen([('异象',974,23,56,31),('本周已获取友好点数514',892,80,240,19),
              ('联结共鸣',956,136,90,24),('20',1060,195,28,21),
              ('可见玩家00:20:10',914,294,240,23),('20',1060,337,28,21)])
    assert copy_rows(s)==[347]
    assert copy_fingerprint(s)==('可见玩家',)


def test_insufficient_stamina_skips_detail_scan_until_free_refill(tmp_path):
    from test_configuration import daily
    d=daily(tmp_path)
    s=screen([('异象',974,23,56,31),('本周已获取友好点数514',892,80,240,19),('13/164',510,15,75,24)])
    d.observe=lambda:s;d.home=lambda:None
    d.copy_targets=lambda *a:pytest.fail('No battle is affordable yet')
    assert '不足20' in d.copy_battles()


def test_actual_clipped_row_with_hidden_name_is_excluded():
    from test_configuration import captured
    s=captured('copy-clipped-list')
    assert copy_rows(s)==[494,630]
    assert copy_fingerprint(s)==('喵喵撸猫中','南岸')
