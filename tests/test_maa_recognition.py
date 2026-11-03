from private_capture import capture_file
"""Run the actual MaaFramework recognition engine against captured game fixtures.

No MuMu process, game connection or input is used in these tests.
"""
import threading
import time
import numpy as np
from PIL import Image
from maa.resource import Resource
from maa.tasker import Tasker
from maa.pipeline import JTemplateMatch,JOCR
from chao2.backend import ROOT,MuMuController,Screen,Word,Backend
from chao2.workflows import is_world,is_start_screen,START_BUTTON,START_BUTTON_ROI

class Offline(MuMuController):
    def __init__(self):super().__init__('unused','offline',threading.Event())
    def connect(self):self.ready=True;return True
    def request_uuid(self):return 'test-offline'
    def screencap(self):return np.zeros((720,1280,3),np.uint8)
    def click(self,*a):raise AssertionError('Recognition test must not click')
    def swipe(self,*a):raise AssertionError('Recognition test must not swipe')

def test_actual_maa_0926_free_costs_zero_score_and_rank_prefix(tmp_path):
    from test_configuration import captured
    from chao2.workflows import Daily
    from chao2.star_shop import spore_offers
    from chao2.puzzle import puzzle_daily_best
    from chao2.daily_challenges import arena_rating
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t
    d=Daily(b,{'folder':tmp_path,'events':[]});d.state_file=tmp_path/'state.json'
    offers=spore_offers(b,captured('v0926-star_spores-blocked',True))
    assert [(o['name'],o['remaining'],o['price']) for o in offers]==[
        ('进化孢子',5,30),('强化孢子',5,30)]
    assert puzzle_daily_best(b,captured('v0926-daily_puzzle-blocked',True))==0
    s=captured('v0926-arena-blocked',True)
    assert arena_rating(s,(790,410,100,50))==1966
    assert d.verify_arena_detail(s,{'name':'可乐味耀变体','rating':1966,'power':1412})==1
    from chao2.daily_challenges import ARENA_CARDS
    assert d.read_arena_power(captured('v0926-arena-live-list',True),ARENA_CARDS[1][0])==11474
    assert d.read_arena_power(captured('v0926-arena-verified',True),(1112,432,91,35))==11474


def test_actual_maa_friend_time_crops_read_low_contrast_days_without_deleting(tmp_path):
    from test_configuration import captured
    from chao2.workflows import Daily
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t
    d=Daily(b,{'folder':tmp_path,'events':[]});d.state_file=tmp_path/'state.json'
    top=d.verified_friend_rows(captured('v0922-friends-top',True))
    assert [x['time'] for x in top]==['3天前','3天前','1天前','1小时前']
    rows=d.verified_friend_rows(captured('v0922-friends-page2',True))
    assert next(x for x in rows if x['name']=='奥比')['days']==7
    assert not d.report.get('friends_removed')
    # At the track's right limit the percent sign is clipped. The three
    # digits must independently read 100 before this free milestone is used.
    progress,marks=d.plane_marks(captured('v0922-plane-first',True))
    assert progress==100 and marks[-1][0]==100
    from chao2.reward_collection import reward_overlay
    reward=captured('v0922-daily-single-reward',True)
    assert not reward_overlay(reward)
    assert reward_overlay(d.calibrate_collection_reward(reward))


def test_actual_capture_grade_survives_name_information_icon_merge(tmp_path):
    from test_configuration import captured
    from chao2.workflows import Daily
    from chao2.wild_capture import wild_identity,capture_values
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t
    d=Daily(b,{'folder':tmp_path,'events':[]});d.state_file=tmp_path/'state.json'
    e={'name':'撼地兽','rarity':'ultimate','traps_used':0}
    before=captured('v0918-wild-before',True)
    _,roi=d.confirm_wild_identity(before,e,'捕捉页')
    after=captured('v0918-wild-info-icon',True)
    assert wild_identity(after)=={'name':None,'rarity':'ultimate'}
    s,_=d.confirm_wild_identity(after,e,'使用捕兽夹后',title_roi=roi)
    assert s is after and capture_values(s)['probability']==60 and capture_values(s)['traps']==107
    assert not d.report.get('wild_identity_crops')


def test_actual_maa_reads_failed_navigation_and_event_screens():
    from test_configuration import captured
    from chao2.daily_challenges import origin_resume_state,rank_change_notice
    from chao2.reward_collection import is_map_story,echo_story_kind,CLAIM,CONTRACT_CLAIM_ROI
    from chao2.forest import forest_collect_ready
    from chao2.anomalies import sage_answer
    from chao2.event_hub import is_event_hub
    from chao2.activities import main_unlock_level,next_tower_floor,is_tribe_detail
    from chao2.transient_popups import is_star_gift
    from chao2.other_tasks import friend_delete_confirmation
    from chao2.reward_collection import task_claim_slot
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t
    for name,check in [('v0914-origin-matching',lambda s:origin_resume_state(s)=='matching'),
                       ('v0914-map-story',is_map_story),
                       ('v0914-forest-collect-glow',lambda s:forest_collect_ready(b,s)),
                       ('v0915-sage-dominance',lambda s:sage_answer(s) is not None and sage_answer(s).text=='霸气越高击退敌人的距离越远'),
                       ('v0916-hub-covered',is_event_hub),
                       ('v0919-rank-demotion',lambda s:rank_change_notice(s).text=='段位下降'),
                       ('v0920-main-story',is_map_story),
                       ('v0920-torrent-comment-icon',lambda s:echo_story_kind(s)=='torrent'),
                       ('v0920-contract-tasks',lambda s:s.find(CLAIM,CONTRACT_CLAIM_ROI)),
                       ('v0921-star-gift',is_star_gift),
                       ('v0921-main-locked',lambda s:main_unlock_level(s)==73),
                       ('v0921-tower-clipped',lambda s:next_tower_floor(s)[0]==302),
                       ('v0921-tribe-detail',is_tribe_detail),
                       ('v0921-friend-confirm',friend_delete_confirmation),
                       ('v0921-daily-ready',task_claim_slot)]:
        im=captured(name,True).image
        result=t.post_recognition('OCR',JOCR(roi=[0,0,1280,720],threshold=.5),im).wait().get()
        words=[Word(v.text,list(v.box),v.score) for n in result.nodes if n.recognition
               for v in n.recognition.all_results if getattr(v,'text','') and v.score>=.5]
        assert check(Screen(im,words,time.monotonic())),name


def test_actual_maa_recovers_forest_challenge_only_with_local_text_and_star():
    from test_configuration import captured
    from chao2.forest import recover_forest_node,ForestNode,forest_nodes,forest_detail,verify_free_forest
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t;s=captured('v0921-forest-ocr',True)
    assert not s.find('^挑战$')
    assert any(n.action=='challenge' and abs(n.point[0]-376)<2 for n in forest_nodes(b,s))
    node=ForestNode('beast',(376,130),'challenge')
    recovered=recover_forest_node(b,s,(376,130),node)
    assert abs(recovered.point[0]-376)<=1 and recovered.point[1]==130
    assert recover_forest_node(b,s,(324,295),node) is None
    assert recover_forest_node(b,s,(646,187),node) is None
    # An icon alone cannot authorize a click after its action has disappeared.
    s.image[114:152,330:422]=0;s.words=[w for w in s.words if w.text!='挑战']
    assert recover_forest_node(b,s,(376,130),node) is None
    assert not any(n.action=='challenge' for n in forest_nodes(b,s))
    event=captured('v0921-forest-explorer',True)
    assert forest_detail(event).startswith('其他探索者')
    verify_free_forest(b,event,forest_detail(event))


def test_actual_maa_finds_only_the_monster_cocoon_and_reads_spending_target():
    from test_configuration import captured
    from chao2.monster_boxes import monster_box_stock,monster_choice_name,is_monster_box_result
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t
    item=captured('v0917-box-item',True)
    assert b.match_template(item,'monster-box-blue.png',(140,88,580,570),.90)
    assert not b.match_template(captured('v090-potion-dialog',True),'monster-box-blue.png',(140,88,580,570),.90)
    for name,check in [('v0917-box-item',lambda s:monster_box_stock(s)==4),
                       ('v0917-box-selected',lambda s:monster_choice_name(s)=='停顿'),
                       ('v0917-box-result',lambda s:is_monster_box_result(s,'行尸'))]:
        im=captured(name,True).image
        result=t.post_recognition('OCR',JOCR(roi=[0,0,1280,720],threshold=.5),im).wait().get()
        words=[Word(v.text,list(v.box),v.score) for n in result.nodes if n.recognition
               for v in n.recognition.all_results if getattr(v,'text','') and v.score>=.5]
        assert check(Screen(im,words,time.monotonic())),name


def test_actual_merchant_arrow_header_and_shop_currency():
    from test_configuration import captured
    from chao2.merchant import merchant_action,select_merchant_offer
    from chao2.merchant_settings import merchant_options
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t
    assert merchant_action(b,captured('v0911-merchant-intro',True))[0]=='dialogue'
    assert merchant_action(b,captured('v0925-merchant-red-dialogue',True))[0]=='dialogue'
    assert merchant_action(b,captured('v0925-merchant-red-choice',True))[0]=='choice:=口拒绝'
    assert merchant_action(b,captured('v0925-merchant-red-reward',True))[0]=='reward'
    s=captured('v0911-merchant-choice',True)
    s.words=[w for w in s.words if w.center[1]>460 or w.text=='神秘商人']
    assert merchant_action(b,s) is None  # Real pixels still show the choices.
    shop=captured('v0911-merchant-shop',True)
    options=merchant_options({'merchant_options':{'mode':'buy','items':[{'id':'spore','enabled':True}]}})
    offer=select_merchant_offer(b,shop,options)
    assert offer and offer['id']=='spore' and offer['price']==240


def test_actual_maa_abyss_stamina_cost_and_unchecked_instant_break():
    from test_configuration import captured
    from chao2.abyss import verify_abyss_entry
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t
    assert verify_abyss_entry(b,captured('v099-abyss-detail',True))==(60,166)


def test_actual_wild_capture_cost_and_success_portrait():
    from test_configuration import captured
    from chao2.workflows import Daily
    from chao2.wild_capture import capture_values,wild_result
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t
    s=captured('v097-wild-missed-one',True)
    assert capture_values(s)['trap_cost'] is None
    assert b.read_number(s,(499,637,18,28))==1
    assert b.match_template(s,'wild-stamina.png',(915,595,65,65),.90)
    d=Daily(b,{'events':[],'folder':ROOT/'tests/fixtures'})
    b.save_screen=lambda *a:None
    s=captured('v097-wild-success',True)
    assert wild_result(s,'幽鬼') is None  # Original OCR missed the level, not a failure.
    assert d.wild_outcome(s,'幽鬼')=='captured'
    assert s.find('^等级1$')


def test_actual_maa_recovers_world_navigation_after_full_frame_ocr_miss():
    from test_configuration import captured
    from chao2.workflows import Daily
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t
    d=Daily(b,{'events':[]});s=captured('v089-world-misread',True)
    assert not is_world(s) and s.find('^世界向响$')
    confirmed=d.recover_world_navigation(s)
    assert is_world(confirmed) and confirmed.find('^事件$')

def test_actual_maa_rift_nodes_and_chest_cost():
    from test_configuration import captured
    from chao2.rift import rift_node,rift_progress,rift_map_keys,verify_free_rift
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t;b.log=lambda _:None
    for fixture,cleared,keys in [('v084-rift-map23',23,6),('v084-rift-map24',24,5),
                               ('v092-rift-map25',25,3)]:
        s=captured(fixture,True)
        assert rift_progress(b,s)==cleared and rift_map_keys(b,s)==keys
        assert rift_node(b,s,cleared)[0]=='open'
        assert rift_node(b,s,cleared+1)[0]=='next'
        assert rift_node(b,s,cleared+2)[0]=='locked'
    verify_free_rift(b,captured('v084-rift-detail24',True),24)
    s=captured('v084-rift-victory24',True)
    assert b.match_template(s,'rift-key-cost.png',[750,480,185,55],.9)
    assert b.match_template(s,'rift-closed-chest.png',[880,335,115,125],.9)
    assert not b.match_template(captured('v084-rift-reward24',True),'rift-closed-chest.png',[880,335,115,125],.9)

def test_actual_maa_forest_point_costs_and_free_actions():
    from test_configuration import captured
    from chao2.forest import forest_nodes,verify_free_forest
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t;b.log=lambda _:None
    s=captured('v085-forest-map',True);nodes=forest_nodes(b,s)
    assert any(n.kind=='beast' and n.action=='explore' and n.cost==1 and n.point==(109,165) for n in nodes)
    assert any(n.kind=='unknown' and n.cost==1 for n in nodes)
    assert b.match_template(s,'forest-collect.png',[1170,520,110,110],.88)
    assert not b.match_template(captured('v085-forest-collected',True),'forest-collect.png',[1170,520,110,110],.88)
    verify_free_forest(b,captured('v085-forest-beast',True),'幼体凶兽')

def test_actual_maa_confirms_cocoon_label_misread_in_overview():
    from test_configuration import captured
    from chao2.workflows import Daily
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t;b.log=lambda _:None
    d=Daily(b,{'events':[]});s=captured('v083-overview-cocoon',True)
    assert s.find('^永生之萤$') and not s.find('^永生之茧$')
    confirmed=d.read_overview_labels(s,{'target':'^永生之茧$'})
    assert confirmed.find('^永生之茧$',(350,80,180,490))

def test_actual_maa_tour_nodes_across_themes_and_free_challenge():
    from test_configuration import captured
    from chao2.tour import tour_node,verify_free_tour
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t
    assert tour_node(b,captured('v081-tour-cyber-map',True),14)==((394,270),'battle')
    red=tour_node(b,captured('v081-tour-red-map',True),3)
    assert red and abs(red[0][0]-220)<5 and red[1]=='battle'
    assert tour_node(b,captured('v081-tour-cyber-map',True),12) is None
    verify_free_tour(b,captured('v081-tour-detail',True),14)

def test_actual_maa_reads_missed_origin_nine_and_confirms_arena_zero():
    from test_configuration import captured
    from chao2.workflows import Daily
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t;d=Daily(b,{'events':[]})
    assert d.read_pvp_quota(captured('v077-origin-nine',True),'origin')==9
    assert d.read_pvp_quota(captured('origin-menu',True),'origin')==13
    assert d.read_pvp_quota(captured('v077-arena-zero',True),'arena')==0

def test_actual_maa_reads_puzzle_tiles_and_empty_cells():
    from test_configuration import captured
    from chao2.puzzle import read_board
    from chao2.puzzle_solver import board_score
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t
    assert read_board(b,captured('puzzle-initial',True))==(0,0,2,0,0,0,0,0,0)
    assert read_board(b,captured('puzzle-two-tiles',True))==(2,0,0,0,0,0,0,2,0)
    assert read_board(b,captured('puzzle-high-tiles',True))==(2,2,8,0,2,8,8,128,32)
    board=read_board(b,captured('puzzle-score-204',True))
    assert board==(32,16,4,8,4,0,2,4,2)
    assert board_score(board)==204  # Full-frame OCR had incorrectly returned 20.

def test_actual_maa_distinguishes_own_experience_from_friend_coin():
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    for file,expected in [('own-reward.png',True),('friend-reward.png',False)]:
        rgb=np.array(Image.open(capture_file(file)).convert('RGB'))
        im=rgb[:,:,::-1].copy()
        result=t.post_recognition('TemplateMatch',JTemplateMatch(template=['copy-own-exp50.png'],roi=[0,0,110,90],threshold=[.88]),im).wait().get()
        hit=any(n.recognition and n.recognition.hit for n in result.nodes)
        assert hit is expected
        friend=t.post_recognition('TemplateMatch',JTemplateMatch(template=['copy-friend-coin.png'],roi=[0,0,110,90],threshold=[.88]),im).wait().get()
        assert any(n.recognition and n.recognition.hit for n in friend.nodes) is not expected

def test_actual_maa_reads_enter_button_from_supplied_title_image():
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    rgb=np.array(Image.open(capture_file('start-screen.png')).convert('RGB').resize((1280,720)))
    im=rgb[:,:,::-1].copy()
    result=t.post_recognition('OCR',JOCR(roi=[0,0,1280,720],threshold=.5),im).wait().get()
    words=[Word(v.text,list(v.box),v.score) for n in result.nodes if n.recognition
           for v in n.recognition.all_results if getattr(v,'text','') and v.score>=.5]
    s=Screen(im,words,time.monotonic())
    Backend({}).guard(s)
    assert is_start_screen(s)
    x,y=s.find(START_BUTTON,START_BUTTON_ROI).center
    assert 580<=x<=700 and 590<=y<=650

def test_actual_maa_recognizes_the_world_frame_that_stopped_the_previous_run():
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    im=np.array(Image.open(capture_file('world-missed-label.png')).convert('RGB'))[:,:,::-1].copy()
    result=t.post_recognition('OCR',JOCR(roi=[0,0,1280,720],threshold=.5),im).wait().get()
    words=[Word(v.text,list(v.box),v.score) for n in result.nodes if n.recognition
           for v in n.recognition.all_results if getattr(v,'text','') and v.score>=.5]
    s=Screen(im,words,time.monotonic())
    Backend({}).guard(s)
    assert is_world(s)


def test_actual_maa_recognizes_exploration_reward_summary_and_scrolled_variant():
    from chao2.activities import is_exploration_rewards,is_exploration_menu
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    for name in ('exploration-rewards','exploration-rewards-scrolled'):
        im=np.array(Image.open(capture_file(name+'.png')).convert('RGB'))[:,:,::-1].copy()
        result=t.post_recognition('OCR',JOCR(roi=[0,0,1280,720],threshold=.5),im).wait().get()
        words=[Word(v.text,list(v.box),v.score) for n in result.nodes if n.recognition
               for v in n.recognition.all_results if getattr(v,'text','') and v.score>=.5]
        s=Screen(im,words,time.monotonic())
        Backend({}).guard(s)
        assert is_exploration_rewards(s)
        assert not is_exploration_menu(s) and not is_world(s)


def test_actual_maa_reads_hunt_stock_and_distinguishes_completed_daily_cards():
    from chao2.workflows import Daily
    from chao2.configuration import COCOON_DAILIES
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t;d=Daily(b,{'events':[]})
    for name,done in [('cocoon-daily-completed',True),('cocoon-daily-available',False),('v076-cocoon-completed',True),('v076-cocoon-particle',True)]:
        import json
        path=capture_file(name+'.png')
        s=Screen(np.array(Image.open(path.with_suffix('.png')).convert('RGB'))[:,:,::-1].copy(),
                 [Word(**w) for w in json.loads(path.with_suffix('.json').read_text('utf-8'))],time.monotonic())
        assert d.cocoon_daily_done(s)==(set(COCOON_DAILIES) if done else set())
    s=Screen(np.array(Image.open(capture_file('hunt-token-stock.png')).convert('RGB'))[:,:,::-1].copy(),[],time.monotonic())
    assert b.read_number(s,(1110,599,77,45))==4
    assert b.read_number(s,(1147,610,36,29)) is None  # Original failing crop included the underline.
    from test_configuration import captured
    s=captured('hunt-three-tokens',True)
    assert b.read_number(s,(1110,599,77,45)) is None
    assert b.read_number(s,(1130,597,56,38))==3


def test_actual_maa_tribe_tiny_war_order_cost_and_team_power():
    from test_configuration import captured
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t
    assert b.read_number(captured('tribe-active-detail',True),(1096,633,25,29))==1
    assert b.read_number(captured('tribe-copied-formation',True),(1178,77,80,35))==58933
    assert b.read_number(captured('tribe-copied-formation',True),(1175,72,100,48)) is None
    from chao2.activities import formation_power
    assert formation_power(b.read_text_crop(captured('v0913-tribe-power',True),(1178,77,80,35)))==74371
    assert formation_power(b.read_text_crop(captured('v0913-team-config',True),(426,103,72,32)))==74371
    from types import SimpleNamespace
    from chao2.tribe_rewards import TribeOccupationRewards
    probe=SimpleNamespace(b=b)
    assert TribeOccupationRewards.read_tribe_occupation_amount(probe,captured('tribe-entry',True))==2
    assert TribeOccupationRewards.read_tribe_occupation_amount(probe,captured('v0936-tribe-entry',True))==10


def test_actual_maa_confirms_both_resource_numbers_when_slash_is_misread():
    from test_configuration import captured
    from chao2.policy import parse_ratio
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t;s=captured('tower-resource-bracket',True)
    roi=(1030,0,170,65)
    assert parse_ratio(s.region_text(roi)) is None
    assert b.read_resource_ratio(s,roi)==(7,20)
    assert b.read_resource_ratio(captured('tower-detail-bracket',True),(1140,0,140,65))==(7,20)

def test_actual_maa_confirms_free_world_ambush_entry():
    from test_configuration import captured
    from chao2.world_events import verify_ambush,ambush_identity
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t;s=captured('v082-ambush',True)
    assert verify_ambush(b,s,ambush_identity(s))==122


def test_friend_copy_without_instant_checkbox_is_not_blocked():
    from test_configuration import captured
    from chao2.workflows import Daily
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t;s=captured('friend-no-instant',True)
    d=Daily(b,{'events':[]})
    assert d.copy_kind(s,(514,1000)) is None  # Friends are off by default.
    d.options['copies']['include_friends']=True
    assert d.copy_kind(s,(514,1000))=='friend'
    d.verify_instant_setting('copies',s)


def test_short_copy_name_missing_from_full_frame_is_recovered_locally():
    from test_configuration import captured
    from chao2.activities import copy_fingerprint
    from chao2.workflows import Daily
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t;d=Daily(b,{'events':[]})
    s=captured('copy-short-name',True)
    assert copy_fingerprint(s)==('梦魔来拍照','','铁匠等好评')
    assert copy_fingerprint(d.read_copy_names(s))==('梦魔来拍照','七十','铁匠等好评')
    assert copy_fingerprint(s)[1]==''  # Keep the original failure evidence intact.


def test_actual_maa_arena_cost_and_zero_rampage_daily_record():
    from test_configuration import captured
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({});b.tasker=t
    assert b.read_number(captured('arena-detail',True),(1041,629,23,27))==1
    assert b.read_number(captured('rampage-menu',True),(1165,406,78,32))==0
    from chao2.workflows import Daily
    d=Daily(b,{'events':[]})
    assert d.rampage_score(captured('rampage-completed',True))==564
    from chao2.daily_challenges import arena_candidates,choose_opponent
    rows=arena_candidates(captured('arena-slanted-power',True),d.read_arena_power)
    assert [row['power'] for row in rows]==[14193,3635,3743,3607]
    assert choose_opponent(rows,'weakest')['index']==3
    detail=captured('arena-detail-slanted',True)
    assert d.read_arena_power(detail,(1112,432,91,35))==31874
    assert d.verify_arena_detail(detail,{'power':31874})==1
    assert d.verify_arena_detail(captured('arena-detail-missed-one',True),{'power':31874})==1
    assert d.verify_arena_detail(captured('arena-detail',True),{'power':3547})==10
    im=np.array(Image.open(capture_file('arena-promotion.png')).convert('RGB'))[:,:,::-1].copy()
    result=t.post_recognition('OCR',JOCR(roi=[0,0,1280,720],threshold=.5),im).wait().get()
    words=[Word(v.text,list(v.box),v.score) for n in result.nodes if n.recognition
           for v in n.recognition.all_results if getattr(v,'text','') and v.score>=.5]
    assert Screen(im,words,time.monotonic()).find('^段位提升$',(450,400,380,150))


def test_actual_maa_tower_territory_reconfirms_cocoon_label_dropped_by_ocr(tmp_path):
    """2026-10-21 15:57 regression: the golden 永生之茧 map label is visible
    but full-frame OCR returns nothing for it, which silently disarmed the
    tower entrance clicks and failed the nest anchor check."""
    from test_configuration import captured
    from chao2.workflows import Daily
    c=Offline();assert c.post_connection().wait().succeeded
    r=Resource();assert r.post_bundle(ROOT/'resource').wait().succeeded
    t=Tasker();assert t.bind(r,c)
    b=Backend({},log=lambda _:None);b.tasker=t
    d=Daily(b,{'folder':tmp_path,'events':[]});d.state_file=tmp_path/'state.json'
    s=captured('v0926-world-cocoon-label',True)
    assert s.find('^永生之茧$',(780,140,210,170)) is None  # documents the dropped label
    assert d.tower_territory(s) is True
    assert s.has('^世界$','^黑暗森林$','^永生之茧$')  # the click anchors now pass
    fresh=captured('v0926-world-cocoon-label',True)
    assert b.confirm_label(fresh,'永生之茧',(780,140,210,170)) is True
    assert fresh.has('^永生之茧$')
