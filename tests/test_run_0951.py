"""Level-label border regression found during the full MuMu run."""
from types import SimpleNamespace
import pytest
from test_configuration import captured,daily
from chao2.backend import Backend,ROOT
from chao2 import star_shop as shop
from chao2.policy import TaskBlocked


def test_actual_maa_purple_level_one_labels_exclude_card_border():
    from maa.resource import Resource
    from maa.tasker import Tasker
    from test_maa_recognition import Offline
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t
    s=captured('v0951-star-candidates',True)
    rows=shop.ultimate_candidates(s)
    assert len(rows)==3
    assert shop.ultimate_level(b,s,rows[0])==1
    assert shop.ultimate_level(b,s,rows[2])==1
    assert shop.ultimate_level(b,s,rows[1])==1
    s=captured('v0951-star-last-purple',True)
    assert shop.ultimate_level(b,s,shop.ultimate_candidates(s)[0])==1


@pytest.mark.parametrize('wide,tight,detected,expected',[
    ('等级10','等级1','等级1',10),
    ('1','等级1','等级1',1),
    ('1','等级10','等级10',10),
    ('1','等级1','等级10',None),
    ('1','1','1',None),
])
def test_fallback_needs_full_matching_level_and_preserves_multiple_digits(wide,tight,detected,expected):
    roi=(834,515,48,25)
    b=SimpleNamespace(read_text_crop=lambda s,r:wide if r==roi else
        tight if r==(834,516,48,22) else detected)
    assert shop.ultimate_level(b,None,{'level_roi':roi})==expected


def test_unreadable_existing_ultimates_do_not_trigger_more_evolution(tmp_path,monkeypatch):
    d=daily(tmp_path,{'task_options':{'other':{'buy_star_spores':True,
        'convert_star_souls':True,'evolve_blue_for_star_souls':True}}})
    s=captured('v0951-star-candidates',True)
    d.open_star_shop=lambda:s;d.wait_for_screen=lambda *a,**k:s
    d.b.click_at=lambda *a:None;d.b.click_text=lambda *a,**k:None;d.b.sleep=lambda *a:None
    d.b.controller=SimpleNamespace(post_swipe=lambda *a:None);d.b.wait=lambda *a:None
    d.b.read_text_crop=lambda *a:''
    d.b.read_text_region=lambda *a,**kw:''
    d.evolve_one_blue_for_star_souls=lambda *a:pytest.fail('Unreadable is not empty inventory')
    monkeypatch.setattr(shop,'star_souls',lambda *a:5)
    monkeypatch.setattr(shop,'star_yield',lambda *a:0)
    with pytest.raises(TaskBlocked,match='未进化或购买补料'):d.convert_one_ultimate(270,5)
