"""Forest points use a fixed HUD crop, with no background or navigation retry."""
import pytest
from test_configuration import daily,screen,captured
from test_rift_main_0959 import offline_backend
from chao2.forest import forest_points,is_forest_map,FOREST_POINTS_ROI
from chao2.policy import TaskBlocked,ResourceReadError,UserStopped
from chao2.page_recovery import navigation_failure


def forest_map():
    s=screen(('黑暗森林',125,17,87,22),('信息',210,665,80,30),
             ('0l6ff;',1124,1,89,66),('开始探索',1120,54,130,30))
    s.image[14:43,122:218]=255
    assert is_forest_map(s)
    return s


def reader(d,answers):
    values=iter(answers);calls=[]
    def local(s,roi,scale=1,threshold=.65):
        calls.append((roi,scale,threshold));return next(values)
    d.b.read_text_region=local
    d.b.read_resource_ratio=lambda *a:pytest.fail('Must not reuse full-frame OCR words')
    d.b.click_at=lambda *a:pytest.fail('Point reads must not click')
    return calls


@pytest.mark.parametrize('texts,expected',[
    (['0/16','0/16'],0),(['5/16','5/16'],5),
    ([' 4 ／ 16 ','4/16'],4),(['16/16','16/16'],16),
    (['','0/16','0/16'],0),(['5/16','5/16;','5/16'],5),
])
def test_point_read_always_uses_fixed_crop_and_two_agreeing_local_results(tmp_path,texts,expected):
    d=daily(tmp_path);s=forest_map();calls=reader(d,texts)
    assert forest_points(d.b,s)==expected
    assert len(calls)==len(texts) and all(roi==FOREST_POINTS_ROI and threshold==.8 for roi,_,threshold in calls)
    assert [scale for _,scale,_ in calls]==[3,4,2][:len(texts)]


@pytest.mark.parametrize('texts',[
    ['','',''],['0l6ff;']*3,['0/0']*3,['-1/16']*3,['1000/16']*3,
    ['0/16','',''],['0/16','1/16'],['0/16','0/17'],
])
def test_invalid_or_conflicting_local_numbers_fail_with_bounded_diagnostics(tmp_path,texts):
    d=daily(tmp_path);calls=reader(d,texts)
    with pytest.raises(ResourceReadError,match='固定区域局部识别') as error:
        forest_points(d.b,forest_map())
    assert len(calls)<=3 and not navigation_failure(error.value)
    assert '3倍=' in str(error.value) and '4倍=' in str(error.value)


def test_correct_full_frame_number_does_not_override_fixed_crop(tmp_path):
    d=daily(tmp_path);s=forest_map()
    next(w for w in s.words if w.text=='0l6ff;').text='16/16'
    reader(d,['0/16','0/16'])
    assert forest_points(d.b,s)==0


def test_forest_must_be_confirmed_before_any_hud_read(tmp_path):
    d=daily(tmp_path);s=forest_map();s.image[:]=0
    d.b.read_text_region=lambda *a,**kw:pytest.fail('Dim background is not a confirmed map')
    with pytest.raises(TaskBlocked,match='地图未确认'):forest_points(d.b,s)


def test_user_stop_during_local_ocr_is_not_converted_or_retried(tmp_path):
    d=daily(tmp_path);calls=[]
    def stopped(*a,**kw):calls.append(1);raise UserStopped('用户停止')
    d.b.read_text_region=stopped
    with pytest.raises(UserStopped):forest_points(d.b,forest_map())
    assert calls==[1]


def test_field_failure_cannot_multiply_inner_and_outer_page_retries(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();d.b.controller=object();s=forest_map()
    d.forest_map=lambda:s;d.forest_record_view=lambda q:None;d.forest_collect=lambda q:q
    d.forest_simple_reenter=lambda e:pytest.fail('A number read must not reenter the map')
    calls=reader(d,['','',''])
    with pytest.raises(ResourceReadError):d.with_page_recovery(d.forest,'黑暗森林')
    assert len(calls)==3
    assert not d.report.get('forest_simple_recoveries') and not d.report.get('page_recoveries')


def test_failed_point_confirmation_during_real_page_reentry_also_stops_retrying(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();d.b.controller=object();s=forest_map();opens=[]
    def enter():
        opens.append(1)
        if len(opens)==1:raise TaskBlocked('森林地图未确认')
        return s
    d.forest_map=enter;d.home=lambda:None;d.forest_record_view=lambda q:None
    d.report['forest_explorations']=[{'status':'started','before':1,'cost':1}]
    calls=reader(d,['','',''])
    with pytest.raises(ResourceReadError):d.with_page_recovery(d.forest,'黑暗森林')
    assert len(calls)==3 and len(opens)==2
    assert len(d.report['forest_simple_recoveries'])==1 and not d.report.get('page_recoveries')


def test_field_read_failure_blocks_only_current_task_and_allows_next_task(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();d.b.controller=object();calls=[]
    def fail():calls.append('forest');raise ResourceReadError('森林探索点未读清')
    d.forest=fail;d.home=lambda:calls.append('return')
    d.rewards=lambda:calls.append('rewards') or '领奖完成'
    d.execute_task('forest');d.execute_task('rewards')
    assert calls==['forest','return','rewards']
    assert d.report['tasks']['forest']['status']=='blocked'
    assert d.report['tasks']['rewards']['status']=='done'
    assert not d.report.get('page_recoveries')


@pytest.mark.parametrize('name,expected',[('zero',0),('five',5),('four',4),('three',3)])
def test_actual_recorded_hud_reads_even_with_corrupt_full_frame_words(offline_backend,name,expected):
    s=captured('v0977-forest-'+name,True)
    assert forest_points(offline_backend,s)==expected
