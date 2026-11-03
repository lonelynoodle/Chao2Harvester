"""Consecutive copies reuse formation without bypassing per-target checks."""
import pytest
from test_configuration import daily,screen
from chao2.activities import encounter_identity
from chao2.policy import TaskBlocked


class CopyRun:
    def __init__(self,tmp_path,teams,targets,failures=(),friend_quota=(400,1000)):
        self.d=daily(tmp_path,{'task_options':{'copies':{'teams':teams,'include_friends':True}}})
        self.targets=list(targets);self.failures=set(failures);self.friend_quota=friend_quota
        self.team=None;self.selections=[];self.challenges=[];self.cost_checks=[]
        self.result=screen()
        self.d.observe=lambda:self.result;self.d.home=lambda:None
        self.d.copy_targets=self.target;self.d.select_team=self.select
        self.d.exit_result=self.exit;self.d.b.click_text=self.challenge
        self.d.b.match_template=self.template;self.d.b.read_number=lambda *a:20
        verify=self.d.verify_stamina_cost
        def cost(s,amount):
            self.cost_checks.append(encounter_identity(s));verify(s,amount)
        self.d.verify_stamina_cost=cost

    def target(self,wanted,excluded):
        target=next(((name,kind) for name,kind in self.targets if (kind==wanted or wanted=='any') and name not in excluded),None)
        if target is None:return None
        name,kind=target
        detail=screen(('敌方阵容',1100,135,100,30),('排阵',824,614,60,30),
                      ('挑战',1060,605,80,30),(name,140,135,180,25),
                      ('100/164',1185,15,80,26),('20',1096,639,28,18))
        return {'identity':name,'kind':kind,'screen':detail,'quota':self.friend_quota}

    def select(self,s,team):
        self.team=team;self.selections.append(team);return s

    def template(self,s,name,*args):
        kind=dict(self.targets)[encounter_identity(s)]
        return name=='instant-off.png' or name==('copy-own-exp50.png' if kind=='own' else 'copy-friend-coin.png')

    def challenge(self,s,pattern):
        assert pattern=='^挑战$|^前往挑战$'
        name=encounter_identity(s);self.challenges.append((name,self.team))
        failed=(name,self.team) in self.failures
        self.result=screen(('挑战失败' if failed else '胜利',100,200,400,50),
                           ('获得奖励',900,300,100,30),('退出',1140,580,60,30))

    def exit(self,s):
        if s.find('胜利'):
            name=self.challenges[-1][0]
            self.targets=[t for t in self.targets if t[0]!=name]


def test_same_team_enters_formation_once_across_own_and_friend_copies(tmp_path):
    game=CopyRun(tmp_path,[2],[('own1','own'),('own2','own'),('friend1','friend')])
    assert '通关3次' in game.d.copy_battles()
    assert game.selections==[2]
    assert game.challenges==[('own1',2),('own2',2),('friend1',2)]
    assert game.cost_checks==['own1','own2','friend1']
    assert game.d.task_counts['copies']==3


def test_fallback_changes_team_and_next_target_obeys_configured_priority(tmp_path):
    game=CopyRun(tmp_path,[1,2],[('own1','own'),('own2','own'),('own3','own')],failures=[('own1',1)])
    assert '通关3次' in game.d.copy_battles()
    assert game.selections==[1,2,1]
    assert game.challenges==[('own1',1),('own1',2),('own2',1),('own3',1)]
    assert game.cost_checks==['own1','own1','own2','own3']


def test_next_task_invocation_confirms_first_team_again(tmp_path):
    game=CopyRun(tmp_path,[2],[('own1','own')])
    game.d.copy_battles()
    game.targets=[('own2','own')]
    game.d.copy_battles()
    assert game.selections==[2,2]


def test_reused_formation_still_rejects_friend_with_exhausted_weekly_quota(tmp_path):
    game=CopyRun(tmp_path,[1],[('own1','own'),('friend1','friend')],friend_quota=(1000,1000))
    with pytest.raises(TaskBlocked,match='奖励类型或额度未确认'):game.d.copy_battles()
    assert game.selections==[1]
    assert game.challenges==[('own1',1)]


def test_failed_team_selection_cannot_be_reused_on_retry(tmp_path):
    game=CopyRun(tmp_path,[2],[('own1','own')])
    def fail(s,team):raise TaskBlocked('排阵尚未确认')
    game.d.select_team=fail
    with pytest.raises(TaskBlocked,match='排阵尚未确认'):game.d.copy_battles()
    assert game.challenges==[]
    game.d.select_team=game.select
    game.d.copy_battles()
    assert game.selections==[2] and game.challenges==[('own1',2)]
