"""Main stage OCR must remain stable across formation navigation."""
from copy import deepcopy
import pytest
from chao2.activities import main_identity,recover_main_detail,is_main_detail
from chao2.policy import TaskBlocked,UserStopped
from test_configuration import captured,daily,screen
from test_rift_main_0959 import offline_backend


def stage(number='712',pixels=False):
    s=captured('v0966-main712',pixels)
    next(w for w in s.words if w.text=='712').text=number
    return s


@pytest.mark.parametrize('number',['7I2','712_','7 12','I712','712Ⅱ',''])
def test_partial_badge_is_not_a_stage(number):
    assert main_identity(stage(number)) is None


def test_title_numbers_cannot_replace_missing_badge():
    s=stage('');s.words+=screen(('712过载副本',180,135,250,40)).words
    assert main_identity(s) is None


@pytest.mark.parametrize('number',['7I2','7','112','', '712'])
def test_actual_badge_corrects_full_frame_ocr_without_mutating_source(offline_backend,number):
    s=stage(number,True);original=deepcopy(s.words)
    fixed=recover_main_detail(offline_backend,s)
    assert main_identity(fixed)=='712' and is_main_detail(fixed)
    assert fixed.when==s.when and s.words==original
    assert fixed.find('^首通奖励$')


@pytest.mark.parametrize('reads',[('712','72'),('7I2','7I2'),('',''),('712','')])
def test_disagreeing_local_reads_invalidate_even_numeric_global_ocr(tmp_path,reads):
    d=daily(tmp_path);d.b.tasker=object();s=stage()
    d.b.read_text_crop=lambda *_:reads[0];d.b.read_text_region=lambda *a,**kw:reads[1]
    fixed=recover_main_detail(d.b,s)
    assert main_identity(fixed) is None and not is_main_detail(fixed)
    assert main_identity(s)=='712'


def setup(tmp_path):
    d=daily(tmp_path);d.b.sleep=lambda _:None
    return d


def test_initial_target_waits_out_wrong_or_partial_frames(tmp_path):
    d=setup(tmp_path);frames=iter([stage('7I2'),stage(),stage()])
    d.observe=lambda:next(frames)
    q=d.stable_main_detail(stage('112'))
    assert main_identity(q)=='712'
    row=d.report['main_identity_checks'][0]
    assert row['readings']==['112',None,'712','712'] and row['status']=='confirmed'
    assert (tmp_path/'main-identity-1-target-0.png').exists()


def test_after_team_waits_for_original_target_and_returns_fresh_screen(tmp_path):
    d=setup(tmp_path);final=stage();frames=iter([stage(),final])
    d.observe=lambda:next(frames)
    assert d.stable_main_detail(stage('112'),'712','after-team') is final
    assert d.report['main_identity_checks'][0]['readings']==['112','712','712']


@pytest.mark.parametrize('number',['713','7I2'])
def test_after_team_never_replaces_expected_target(tmp_path,number):
    d=setup(tmp_path);reads=[];d.observe=lambda:reads.append(1) or stage(number)
    with pytest.raises(TaskBlocked,match='原目标712.*重读4次'):
        d.stable_main_detail(stage(number),'712','after-team')
    assert len(reads)==4 and d.battles==0
    assert d.report['main_identity_checks'][0]['status']=='unconfirmed'


def test_stability_does_not_ignore_stop(tmp_path):
    d=setup(tmp_path)
    def stop():raise UserStopped('用户停止')
    d.b.check_stop=stop
    with pytest.raises(UserStopped):d.stable_main_detail(stage())


def test_real_encounter_uses_recovered_post_team_frame_for_verification_and_start(tmp_path):
    d=setup(tmp_path);d.options['main']['teams']=[2];d.active_task='main'
    source=stage();fresh=stage();calls=[];frames=iter([fresh,fresh])
    d.select_team=lambda *_:stage('112');d.observe=lambda:next(frames)
    d.verify_instant_setting=lambda *_:None
    d.start_challenge=lambda task,s,*args:calls.append(('start',s))
    d.battle=lambda *_:screen(('胜利',100,200,80,30))
    d.exit_result=lambda *_:None
    assert d.play_encounter('main',lambda:source,'主线体力5',lambda s:calls.append(('verify',s)))
    assert calls==[('verify',fresh),('start',fresh)]
    assert d.report['team_attempts'][0]['target']=='712'


def test_real_encounter_blocks_changed_stage_before_any_challenge(tmp_path):
    d=setup(tmp_path);d.options['main']['teams']=[2]
    d.select_team=lambda *_:stage('713');d.observe=lambda:stage('713')
    d.start_challenge=lambda *_:pytest.fail('Changed stage cannot start')
    with pytest.raises(TaskBlocked,match='原目标712'):
        d.play_encounter('main',lambda:stage(),'主线体力5')
    assert d.battles==0 and not d.report.get('team_attempts')
