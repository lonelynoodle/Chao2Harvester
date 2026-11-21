"""Verified displayed balances. Compact units are intervals, never exact sums."""
import re
from decimal import Decimal
from .policy import TaskBlocked

BALANCE_PATTERN=r'^\d+(?:\.\d{1,4})?[万亿]?$'

def displayed_balance(text):
    if not re.fullmatch(BALANCE_PATTERN,text):return None
    if text.isdigit():return int(text)
    match=re.fullmatch(r'(\d+(?:\.\d{1,4})?)([万亿])',text)
    if not match:return None
    number,unit=match.groups();factor=10000 if unit=='万' else 100000000
    decimals=len(number.split('.')[1]) if '.' in number else 0
    quantum=factor//10**decimals
    if quantum<1:return None
    center=int(Decimal(number)*factor)
    # Retain uncertainty from either truncation or rounding in the client.
    # Item inventory + the exact confirmed fee/receipt establish the transfer;
    # this display can only check that the transfer is consistent with it.
    return {'text':text,'min':max(0,center-quantum+1),'max':center+quantum-1}

def balance_bounds(balance):
    return (balance,balance) if type(balance) is int else (balance['min'],balance['max'])

def balance_delta_possible(before,after,delta):
    lo,hi=balance_bounds(before);a,z=balance_bounds(after)
    return max(lo+delta,a)<=min(hi+delta,z)

def read_fixed_balance(b,s,roi):
    """Read the complete HUD field, not a possibly truncated full-frame box."""
    confirmed=None;reads=[]
    for scale in (3,4,2):
        raw=b.read_text_region(s,roi,scale=scale,threshold=.8)
        text=re.sub(r'\s','',raw);value=displayed_balance(text)
        reads.append(f'{scale}倍={raw!r}')
        if value is None:continue
        if confirmed is not None:
            if text==confirmed[0]:return value
            break
        confirmed=(text,value)
    raise TaskBlocked('钻石余额固定区域未读清或局部识别不一致（'+'；'.join(reads)+'）')


def read_displayed_balance(b,s,roi):
    word=s.find(BALANCE_PATTERN,roi)
    if not word or word.score<.8:raise TaskBlocked('钻石余额未读清')
    value=displayed_balance(word.text)
    if value is None:raise TaskBlocked('钻石余额格式未确认')
    x,y,w,h=word.box
    if type(value) is int:
        if b.read_number(s,(x-2,y-2,w+4,h+4))!=value:raise TaskBlocked('钻石余额两次识别不一致')
        return value
    local=re.sub(r'\s','',b.read_text_crop(s,(x-2,y-2,w+4,h+4)))
    if local!=word.text:
        reads=[re.sub(r'\s','',b.read_text_region(s,roi,scale=k,threshold=.8)) for k in (2,3)]
        if reads!=[word.text,word.text]:raise TaskBlocked('钻石余额两次识别不一致')
    return value
