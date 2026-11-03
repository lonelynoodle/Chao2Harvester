"""Real capture page + simulated resource/settlement transitions. No game input."""
import copy
import time
import cv2
import numpy as np
import pytest
from chao2.backend import Word
from chao2.policy import TaskBlocked,SafetyStop,UserStopped
from chao2.wild_settings import wild_options,wild_switch,wild_enabled,required_traps,RARITIES
from chao2.configuration import normalize_settings
from chao2.wild_capture import (wild_identity,capture_values,colored_rarity,is_wild_offer,
                               is_wild_capture,wild_result,is_wild_list,wild_cards)
from chao2.workflows import is_world
from test_configuration import daily,captured,screen


def configured(tmp_path,probability=80):
    d=daily(tmp_path,{'wild_capture':{'ultimate':{'enabled':True,'probability':probability}}})
    d.b.sleep=lambda _:None;d.b.match_template=lambda *a:True
    d.b.read_number=lambda *a:None
    d.b.read_text_crop=lambda *a:''
    d.b.save_screen=lambda *a:None;d.checkpoint=lambda:None
    inputs=[];d.b.click_at=lambda s,pt,*args:inputs.append(pt)
    return d,inputs


def page(probability=50,traps=88):
    s=captured('v097-wild-capture',True)
    for w in s.words:
        if w.text=='成功率50%':w.text=f'成功率{probability}%'
        if w.text=='88':w.text=str(traps)
    return s


def entry():return {'name':'幽鬼','rarity':'ultimate','traps_used':0}


def test_new_install_disabled_and_legacy_selection_preserved():
    options=wild_options({})
    assert not wild_enabled({}) and all(not x['enabled'] for x in options.values())
    assert [v['probability'] for v in options.values()]==[80,90,80,100,100]
    assert set(options)==set(RARITIES)
    assert wild_enabled({'wild_capture':{'ultimate':{'enabled':True}}})
    assert not wild_enabled({'wild_capture':{'ultimate':{'enabled':False,'probability':100}}})
    assert not wild_switch({})
    assert normalize_settings({'wild_capture':{'ultimate':{'enabled':True}}})['wild_capture_enabled']


@pytest.mark.parametrize('enabled,selected,effective',[(False,True,False),(True,True,True),(True,False,False),(False,False,False)])
def test_independent_switch_requires_selected_grade(enabled,selected,effective):
    settings=normalize_settings({'wild_capture_enabled':enabled,'wild_capture':{'ultimate':{'enabled':selected,'probability':85}}})
    assert wild_switch(settings)==enabled
    assert wild_enabled(settings)==effective
    assert settings['wild_capture']['ultimate']=={'enabled':selected,'probability':85}


@pytest.mark.parametrize('invalid',[1,0,'true',None])
def test_invalid_master_switch_rejected_before_input(invalid):
    with pytest.raises(ValueError):normalize_settings({'wild_capture_enabled':invalid})


def test_switch_off_blocks_navigation_and_direct_capture_without_losing_choices(tmp_path):
    d,inputs=configured(tmp_path);d.b.settings['wild_capture_enabled']=False;s=page()
    d.observe=lambda *a:pytest.fail('Switch is off')
    d.open_wild_list=lambda *a:pytest.fail('Switch is off')
    assert d.maybe_capture_wild(s) is s
    with pytest.raises(SafetyStop,match='已关闭'):d.capture_wild(s,entry(),{'stamina':40})
    assert inputs==[] and d.b.settings['wild_capture']['ultimate']['enabled']


@pytest.mark.parametrize('bad',[0,101,81,80.0,True,'80',None])
def test_invalid_step_or_type_is_rejected(bad):
    with pytest.raises(ValueError):wild_options({'wild_capture':{'ultimate':{'probability':bad}}})


@pytest.mark.parametrize('raw',[{'enabled':True},{'foo':{}},{'ultimate':True},{'ultimate':{'enabled':1}},None,[]])
def test_invalid_config_does_not_enable_feature(raw):
    with pytest.raises(ValueError):wild_options({'wild_capture':raw})


@pytest.mark.parametrize('current,target,amount',[(50,80,6),(80,80,0),(85,80,0),(50,100,10),(76,80,1)])
def test_preflight_trap_math(current,target,amount):assert required_traps(current,target)==amount


def test_real_page_grade_name_cost_stock_and_ocr_missing_badge():
    s=page()
    assert is_wild_capture(s) and not is_world(s)
    assert wild_identity(s)=={'name':'幽鬼','rarity':'ultimate'}
    assert capture_values(s)=={'probability':50,'traps':88,'cost':20,'increment':5,'trap_cost':1}
    s=captured('v097-wild-offer',True)
    assert is_wild_offer(s) and not is_world(s)
    assert wild_identity(s)=={'name':'幽鬼','rarity':'ultimate'}


@pytest.mark.parametrize('grade,hue',[('young',60),('phantom',105),('ultimate',136),('immortal',25),('awakened',2),('awakened',178)])
def test_color_rarity_uses_name_region_only(grade,hue):
    s=screen();hsv=np.full((25,70,3),(hue,180,210),dtype=np.uint8)
    s.image[10:35,600:670]=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
    assert colored_rarity(s,(600,10,70,25))==grade
    assert colored_rarity(s,(0,0,20,20)) is None


def test_no_default_color_for_unknown_or_mixed_rarity():
    s=page();s.image[10:65,510:800]=128
    assert wild_identity(s)['rarity'] is None


def test_actual_wild_tab_does_not_confuse_exploration_and_name_edge_artifacts():
    s=captured('v097-wild-list',True)
    assert is_wild_list(s) and len(wild_cards(s))==1
    assert wild_cards(s)[0].text.startswith('野生-幽鬼')
    assert not is_wild_list(captured('exploration-menu',True))
    s=page();s.words.append(Word('觉醒',[535,18,35,25],.99))
    assert wild_identity(s)['rarity'] is None


def test_all_unchecked_performs_no_extra_read_navigation_or_reminder(tmp_path):
    d=daily(tmp_path);s=screen()
    d.observe=lambda *a:pytest.fail('Disabled means no reads')
    d.open_wild_list=lambda *a:pytest.fail('Disabled means no navigation')
    assert d.maybe_capture_wild(s) is s and 'wild_captures' not in d.report


@pytest.mark.parametrize('stamina,stock,status',[(19,88,'insufficient_stamina'),(20,5,'insufficient_traps'),(None,88,'insufficient_stamina')])
def test_preflight_insufficient_resource_spends_nothing(tmp_path,stamina,stock,status):
    d,inputs=configured(tmp_path);e=entry()
    d.capture_wild(page(traps=stock),e,{'stamina':stamina})
    assert inputs==[] and e['status']==status and e['traps_used']==0


def test_unchecked_rarity_cannot_use_traps_or_capture(tmp_path):
    d,inputs=configured(tmp_path);d.b.settings['wild_capture']['ultimate']['enabled']=False
    with pytest.raises(SafetyStop,match='未勾选'):d.capture_wild(page(),entry(),{'stamina':40})
    assert inputs==[]


@pytest.mark.parametrize('damage',['template','missing-stock','wrong-cost','wrong-grade'])
def test_unknown_or_changed_capture_cost_never_spends(tmp_path,damage):
    d,inputs=configured(tmp_path);s=page()
    if damage=='template':d.b.match_template=lambda *a:False
    elif damage=='missing-stock':s.words=[w for w in s.words if w.text!='88']
    elif damage=='wrong-cost':
        for w in s.words:
            if w.text=='20':w.text='25'
    else:
        s.words.append(Word('觉醒',[535,18,35,25],.99))
    d.observe=lambda *a:copy.deepcopy(s)
    with pytest.raises((TaskBlocked,SafetyStop)):d.capture_wild(s,entry(),{'stamina':40})
    assert inputs==[]


def prepare_frames(d,frames):
    frames=iter(frames);d.observe=lambda *a:next(frames)
    def wait(predicate,message,seconds=18):
        for _ in range(3):
            s=d.observe()
            if predicate(s):return s
        raise TaskBlocked(message)
    d.wild_wait=wait


def test_six_traps_reach_80_then_capture_once_and_record_actual_success(tmp_path):
    d,inputs=configured(tmp_path);e=entry()
    frames=[page(p,88-i) for i,p in enumerate(range(55,81,5),1)]
    frames += [page(80,82),screen(('捕捉成功',500,200,150,45))]
    prepare_frames(d,frames)
    d.capture_wild(page(),e,{'stamina':54})
    assert inputs==[(481,618)]*6+[(836,632)]
    assert e['traps_used']==6 and e['stock_after']==82 and e['probability']==80
    assert e['status']=='captured' and e['message']=='成功捕捉究极怪兽-幽鬼'


def test_probability_already_at_threshold_uses_zero_traps(tmp_path):
    d,inputs=configured(tmp_path);e=entry()
    prepare_frames(d,[page(85,0),screen(('捕捉失败',500,200,150,45))])
    d.capture_wild(page(85,0),e,{'stamina':20})
    assert inputs==[(836,632)] and e['traps_used']==0 and e['status']=='escaped'


@pytest.mark.parametrize('after',[page(50,87),page(55,88),page(50,88)])
def test_no_retry_on_uncertain_trap_spend(tmp_path,after):
    d,inputs=configured(tmp_path);prepare_frames(d,[copy.deepcopy(after) for _ in range(3)])
    with pytest.raises(TaskBlocked,match='未同时确认'):d.capture_wild(page(),entry(),{'stamina':54})
    assert inputs==[(481,618)]


def test_delayed_trap_feedback_is_only_observed_not_reclicked(tmp_path):
    d,inputs=configured(tmp_path,55);e=entry()
    prepare_frames(d,[page(),page(55,87),page(55,87),screen(('捕捉失败',500,200,150,45))])
    d.capture_wild(page(),e,{'stamina':54})
    assert inputs==[(481,618),(836,632)] and e['status']=='escaped'


def test_generic_rewards_and_fragments_do_not_claim_full_capture():
    assert wild_result(screen(('获得奖励',500,100,150,45)),'幽鬼') is None
    assert wild_result(screen(('获得奖励',500,100,150,45),('幽鬼碎片',500,300,150,45)),'幽鬼')=='fragments'


def test_scan_throttle_does_not_reopen_wild_after_every_task(tmp_path):
    d,_=configured(tmp_path);d._wild_scan_at=time.monotonic();s=screen()
    d.open_wild_list=lambda *a:pytest.fail('No duplicate scan')
    assert d.maybe_capture_wild(s) is s


def unreadable_title(s):
    s.words=[w for w in s.words if not (580<=w.center[0]<800 and w.center[1]<75)]
    return s


def unreadable_grade(s):
    s.image[10:65,510:800]=128
    s.words=[w for w in s.words if not (510<=w.center[0]<800 and w.center[1]<75)]
    return s


def test_real_info_icon_artifact_is_not_a_changed_monster(tmp_path):
    d,inputs=configured(tmp_path,60)
    before=captured('v0918-wild-before',True);after=captured('v0918-wild-info-icon',True)
    assert wild_identity(before)=={'name':'撼地兽','rarity':'ultimate'}
    assert wild_identity(after)=={'name':None,'rarity':'ultimate'} and after.find('^撼地兽C$')
    e={'name':'撼地兽','rarity':'ultimate','traps_used':0}
    s,roi=d.confirm_wild_identity(before,e,'捕捉页')
    d.b.read_text_crop=lambda s,box:'撼地兽' if box==roi else ''
    result,used_roi=d.confirm_wild_identity(after,e,'使用捕兽夹后',title_roi=roi)
    assert result is after and used_roi==roi and inputs==[]
    assert not d.report.get('wild_identity_crops')
    assert after.find('^撼地兽C$')  # The original OCR is preserved for diagnosis.


def test_second_trap_spend_is_saved_before_a_grade_error(tmp_path):
    d,inputs=configured(tmp_path);e=entry()
    frames=[page(55,87)]+[unreadable_grade(page(60,86)) for _ in range(4)]
    prepare_frames(d,frames)
    with pytest.raises(TaskBlocked,match='未读清，已重试3次'):
        d.capture_wild(page(),e,{'stamina':54})
    assert inputs==[(481,618)]*2
    assert (e['traps_used'],e['stock_after'],e['probability'])==(2,86,60)
    assert [r['attempt'] for r in d.report['wild_identity_retries']]==[1,2,3]


def test_missing_name_does_not_block_readable_grade_or_require_extra_traps(tmp_path):
    d,inputs=configured(tmp_path,55);e=entry()
    frames=[unreadable_title(page(55,87)),unreadable_title(page(55,87)),screen(('捕捉成功',500,200,150,45))]
    prepare_frames(d,frames)
    d.capture_wild(page(),e,{'stamina':54})
    assert inputs==[(481,618),(836,632)] and e['traps_used']==1 and e['status']=='captured'
    assert not d.report.get('wild_identity_retries')


def test_crop_confirmation_recovers_without_an_extra_frame_or_click(tmp_path):
    d,inputs=configured(tmp_path,55);e=entry();reads=[]
    d.b.read_text_crop=lambda s,roi:reads.append(roi) or '幽鬼'
    prepare_frames(d,[unreadable_title(page(55,87)),unreadable_title(page(55,87)),
                      screen(('捕捉失败',500,200,150,45))])
    d.capture_wild(page(),e,{'stamina':54})
    assert inputs==[(481,618),(836,632)] and e['status']=='escaped'
    assert reads==[] and not d.report.get('wild_identity_crops')


def test_a_different_ocr_name_does_not_block_same_grade(tmp_path):
    d,inputs=configured(tmp_path,55);e=entry();bad=page(55,87)
    for w in bad.words:
        if w.text=='幽鬼':w.text='幽电'
    prepare_frames(d,[bad,page(55,87),screen(('捕捉成功',500,200,150,45))])
    d.capture_wild(page(),e,{'stamina':54})
    assert inputs==[(481,618),(836,632)] and not d.report.get('wild_identity_retries')


def test_name_is_optional_when_grade_and_resource_state_stay_verified(tmp_path):
    d,inputs=configured(tmp_path,55);e=entry();bad=page(55,87)
    for w in bad.words:
        if w.text=='幽鬼':w.text='别的'
    d.b.read_text_crop=lambda *a:pytest.fail('Do not crop away a different name')
    prepare_frames(d,[copy.deepcopy(bad),copy.deepcopy(bad),screen(('捕捉成功',500,200,150,45))])
    d.capture_wild(page(),e,{'stamina':54})
    assert inputs==[(481,618),(836,632)] and e['traps_used']==1 and e['status']=='captured'
    assert not d.report.get('wild_identity_retries')


def test_missing_rarity_never_defaults_to_expected_color(tmp_path):
    d,inputs=configured(tmp_path,55);e=entry();bad=page(55,87)
    bad.image[10:65,510:800]=128
    d.b.read_text_crop=lambda *a:'幽鬼'
    prepare_frames(d,[copy.deepcopy(bad) for _ in range(4)])
    with pytest.raises(TaskBlocked,match='品级未读清'):
        d.capture_wild(page(),e,{'stamina':54})
    assert inputs==[(481,618)] and e['traps_used']==1


def test_resource_change_during_identity_retry_prevents_more_inputs(tmp_path):
    d,inputs=configured(tmp_path);e=entry()
    prepare_frames(d,[unreadable_grade(page(55,87)),page(60,86)])
    with pytest.raises(TaskBlocked,match='核对怪兽期间'):
        d.capture_wild(page(),e,{'stamina':54})
    assert inputs==[(481,618)] and e['traps_used']==1


def test_initial_title_can_recover_before_spending(tmp_path):
    d,inputs=configured(tmp_path,50);e=entry()
    prepare_frames(d,[page(),page(),screen(('捕捉成功',500,200,150,45))])
    d.capture_wild(unreadable_title(page()),e,{'stamina':54})
    assert inputs==[(836,632)] and e['traps_used']==0


def test_user_stop_aborts_identity_retry_without_input(tmp_path):
    d,inputs=configured(tmp_path);e=entry()
    d.b.sleep=lambda _:(_ for _ in ()).throw(UserStopped('用户停止'))
    with pytest.raises(UserStopped):d.confirm_wild_identity(unreadable_grade(page()),e,'捕捉页')
    assert inputs==[]
