"""Actual thin quantity 1 is blank in the legacy crop; never guess a quantity."""
import pytest
from chao2.stamina_inventory import potion_quantity
from test_configuration import captured,daily,screen
from test_rift_main_0959 import offline_backend


def test_actual_one_is_confirmed_by_two_other_crops(offline_backend):
    s=captured('v0992-potion-dialog',True)
    assert offline_backend.read_number(s,(615,352,55,45)) is None
    assert potion_quantity(offline_backend,s)==1


@pytest.mark.parametrize('reads,expected',[
    (('1','1'),1),(('1','11'),None),(('1',''),None),
    (('一','一'),None),(('1/1','1/1'),None),(('2','2'),2),(('10','10'),10)])
def test_crop_fallback_requires_complete_agreeing_digits(tmp_path,reads,expected):
    d=daily(tmp_path);d.b.tasker=object();d.b.read_number=lambda *a:None
    answers=iter(reads);d.b.read_text_crop=lambda *a:next(answers)
    assert potion_quantity(d.b,captured('v0992-potion-dialog'))==expected


@pytest.mark.parametrize('quantity',[2,10,100])
def test_readable_non_one_must_not_be_overridden_by_tighter_crops(tmp_path,quantity):
    d=daily(tmp_path);d.b.tasker=object();d.b.read_number=lambda *a:quantity
    d.b.read_text_crop=lambda *a:pytest.fail('Do not crop a non-one into one')
    assert potion_quantity(d.b,captured('v0992-potion-dialog'))==quantity


def test_unknown_dialog_does_not_read_quantity(tmp_path):
    d=daily(tmp_path);d.b.tasker=object();d.b.read_number=lambda *a:pytest.fail('Wrong dialog')
    assert potion_quantity(d.b,screen(('确定',750,450,80,30))) is None
