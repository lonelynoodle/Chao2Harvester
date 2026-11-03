"""A misread bracket must not invent or bypass an instant-clear checkbox."""
import pytest

from chao2.anomalies import evolved_copy_without_instant,instant_checkbox_present,instant_frame
from chao2.backend import Word
from chao2.policy import TaskBlocked
from test_configuration import captured,daily
from test_run_0923 import templates


def test_actual_round_bracket_evolved_banner_has_no_instant_toggle(tmp_path):
    s=captured('v0954-copy-evolved',True);d=daily(tmp_path);templates(d.b)
    assert s.find('暴进').text=='(暴进I】大锅盔'
    assert not instant_checkbox_present(s) and evolved_copy_without_instant(s)
    d.verify_instant_setting('copies',s)


@pytest.mark.parametrize('missing',['敌方阵容','排阵','前往挑战','20'])
def test_round_bracket_still_requires_all_evolved_layout_anchors(missing):
    s=captured('v0954-copy-evolved',True)
    s.words=[w for w in s.words if w.text!=missing]
    assert not evolved_copy_without_instant(s)


@pytest.mark.parametrize('checked',[False,True])
def test_visible_checkbox_is_never_bypassed_by_round_bracket_banner(tmp_path,checked):
    s=captured('v0954-copy-evolved',True);d=daily(tmp_path)
    template,_=instant_frame();h,w=template.shape[:2]
    s.image[685:685+h,1010:1010+w]=template
    if checked:s.image[695:704,1020:1029]=255
    assert instant_checkbox_present(s) and not evolved_copy_without_instant(s)
    d.b.match_template=lambda q,name,*a:name=='copy-own-exp50.png'
    with pytest.raises(TaskBlocked,match='瞬破'):d.verify_instant_setting('copies',s)


def test_visible_instant_text_keeps_the_original_guard():
    s=captured('v0954-copy-evolved',True);s.words.append(Word('瞬破',[1060,685,60,30],.99))
    assert not evolved_copy_without_instant(s)
