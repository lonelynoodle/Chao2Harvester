"""A cleared rift node's tether must not obscure its narrow stage number."""
import pytest
from maa.resource import Resource
from maa.tasker import Tasker
from chao2.backend import Backend,ROOT
from chao2.rift import rift_node
from test_configuration import captured
from test_maa_recognition import Offline


@pytest.fixture
def backend():
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t
    return b


def test_actual_maa_recognizes_cleared31_next32_and_locked33(backend):
    s=captured('v0961-rift-node31',True)
    assert backend.read_text_crop(s,(370,435,42,28))!='31'
    node=rift_node(backend,s,31)
    assert node[0]=='open' and abs(node[1][0]-391)<3 and abs(node[1][1]-405)<3
    assert rift_node(backend,s,32)[0]=='next'
    assert rift_node(backend,s,33)[0]=='locked'


@pytest.mark.parametrize('answers',[('3','3'),('31','3'),('|31','31'),('','')])
def test_visible_number_alone_does_not_authorize_node(backend,answers):
    s=captured('v0961-rift-node31',True);calls=[]
    def read(_,roi):
        calls.append(roi)
        return answers[(len(calls)-1)%2]
    backend.read_text_crop=read
    assert rift_node(backend,s,31) is None
    assert (376,437,26,21) in calls


def test_progress_hidden_by_announcement_is_reobserved_before_any_node(tmp_path):
    from test_configuration import daily
    from chao2.backend import Word
    from copy import deepcopy
    d=daily(tmp_path);covered=captured('v0961-rift-progress-covered',True)
    clear=deepcopy(covered)
    clear.words=[w for w in clear.words if not 30<w.center[1]<80]
    clear.words.append(Word('31',[623,35,34,28],.99))
    d.b.read_number=lambda *a:None;d.b.sleep=lambda _:None
    pages=iter([covered,clear]);d.observe=lambda:next(pages)
    located=[]
    d.rift_locate=lambda s,n:located.append((s,n)) or (s,('next',(510,440)))
    d.rift_open_stage=lambda s,n:captured('v084-rift-detail24')
    _,stage=d.rift_highest(covered)
    assert stage==32 and located==[(clear,32)]
    assert len(d.report['navigation_retries'])==2


def test_still_hidden_progress_stops_after_three_rereads_without_navigation(tmp_path):
    from test_configuration import daily
    from chao2.policy import TaskBlocked
    d=daily(tmp_path);s=captured('v0961-rift-progress-covered',True)
    reads=[];d.observe=lambda:reads.append(1) or s
    d.b.read_number=lambda *a:None;d.b.sleep=lambda _:None
    d.rift_locate=lambda *a:pytest.fail('No inferred stage')
    with pytest.raises(TaskBlocked,match='重读3次'):d.rift_highest(s)
    assert len(reads)==3 and d.battles==0


def test_progress_recovery_stops_when_map_changes(tmp_path):
    from test_configuration import daily,screen
    from chao2.policy import TaskBlocked
    d=daily(tmp_path);d.observe=lambda:screen()
    d.b.read_number=lambda *a:None;d.b.sleep=lambda _:None
    d.rift_locate=lambda *a:pytest.fail('No navigation from changed page')
    with pytest.raises(TaskBlocked,match='地图未确认'):
        d.rift_highest(captured('v0961-rift-progress-covered',True))


def test_stop_during_covered_progress_does_not_locate_node(tmp_path):
    from test_configuration import daily
    from chao2.policy import UserStopped
    d=daily(tmp_path);s=captured('v0961-rift-progress-covered',True)
    d.b.read_number=lambda *a:None;d.observe=lambda:s
    d.b.sleep=lambda _:d.b.stop.set()
    with pytest.raises(UserStopped):d.rift_highest(s)
