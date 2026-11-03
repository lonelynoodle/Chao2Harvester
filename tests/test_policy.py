from chao2.policy import can_claim_stamina,dangerous_dialog,friend_allowed,parse_ratio,ResourceAmount

def test_free_stamina_requires_room_and_known_balance():
    assert can_claim_stamina(59,159)
    assert not can_claim_stamina(60,159)
    assert not can_claim_stamina(None,159)
    assert not can_claim_stamina(200,159)

def test_weekly_friend_cap_never_guessed():
    assert friend_allowed(418,1500)
    assert not friend_allowed(1500,1500)
    assert not friend_allowed(None,1500)

def test_buy_dialogs_fail_closed_but_rewards_are_allowed():
    for s in ['是否消耗50钻石购买尖刺？取消 确定','体力不足','确认重置黑暗森林','购买体力']:
        assert dangerous_dialog(s)
    assert not dangerous_dialog('获得 极化石 5 钻石 50 点击空白关闭')
    assert not dangerous_dialog('每日三发 已领取')

def test_resource_recovery_and_ocr_normalization():
    assert parse_ratio('1O／159')==(10,159)
    assert parse_ratio('无法确认') is None
    assert ResourceAmount(18,159).refill_minutes(6)==846
    assert not ResourceAmount(0,20).enough(1)
