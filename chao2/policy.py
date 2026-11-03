import re
from dataclasses import dataclass

class SafetyStop(RuntimeError):
    pass

class PageChanged(SafetyStop):
    """The button vanished before input; retain the actual rechecked frame."""
    def __init__(self,pattern,screen=None):
        super().__init__('点击前页面改变：'+pattern)
        self.pattern=pattern;self.screen=screen

class UserStopped(RuntimeError):
    pass

class TaskBlocked(RuntimeError):
    pass

class ChallengeLocked(TaskBlocked):
    """An explicit level gate; skip this target without counting a battle."""
    def __init__(self,level,screen):
        super().__init__(f'需要探索者等级{level}解锁，跳过当前关卡')
        self.level=level;self.screen=screen

class EncounterInterrupted(TaskBlocked):
    """A map event replaced a requested battle before it started."""
    pass

class FightLost(TaskBlocked):
    def __init__(self,screen):
        super().__init__('挑战失败')
        self.screen=screen

FORBIDDEN = ('购买', '补充次数', '补充体力', '购买体力', '钻石不足', '充值', '极化石', '确认重置', '重置森林', '体力药水', '体力瓶')

def dangerous_dialog(text: str) -> bool:
    """Only classify actual confirmation/buy dialogs, not ordinary reward labels."""
    s = re.sub(r'\s', '', text)
    return (any(w in s for w in ('购买次数', '购买尖刺', '购买羽毛', '购买战令', '补充体力', '是否购买', '是否消耗', '是否重置', '确认重置', '钻石不足', '体力不足', '尖刺不足', '羽毛不足', '战令不足', '征战令不足', '购买体力'))
            or ('取消' in s and any(w in s for w in ('购买', '消耗', '钻石', '重置', '药水', '极化'))))

def is_stamina_potion_dialog(s):
    return bool(s.find('^移动力药水$',(545,260,200,45)) and
                s.find(r'^已拥有\s*\d+$',(550,300,210,45)) and
                s.find('^使用数量$',(300,345,145,65)) and
                s.find('^取消$',(420,440,130,65)) and s.find('^确定$',(745,440,130,65)) and
                not re.search('购买|消耗钻石|充值|重置|极化|补充次数',s.text))

def can_claim_stamina(current: int | None, cap: int | None, gain=100) -> bool:
    return current is not None and cap is not None and 0 <= current <= cap and current + gain <= cap

def friend_allowed(points: int | None, cap: int | None) -> bool:
    return points is not None and cap is not None and 0 <= points < cap

def parse_ratio(text: str) -> tuple[int, int] | None:
    s = text.replace('O','0').replace('o','0').replace('I','1').replace('l','1').replace('／','/')
    m = re.search(r'(\d+)\s*/\s*(\d+)', s)
    return (int(m[1]), int(m[2])) if m else None

@dataclass(frozen=True)
class ResourceAmount:
    current: int
    cap: int

    def enough(self, cost: int) -> bool:
        return cost > 0 and self.current >= cost

    def refill_minutes(self, interval: int) -> int:
        return max(0, self.cap - self.current) * interval
