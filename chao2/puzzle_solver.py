"""3x3 expectimax. Row evaluation follows nneonneo/2048-ai (MIT).

Unlike standard 2048, the observed game's rules spawn only a 2, uniformly
in an empty cell. This bounded search chooses the best evaluated move; it
does not claim a globally optimal policy or predict the random spawn.
"""
from functools import lru_cache
import time

DIRECTIONS=('left','up','right','down')
# With only 2 spawns and no tile removal, the i-th largest tile on nine
# cells is at most 2**(10-i). Merging preserves that bound; creating a second
# tile of the same maximum needs one more cell. The maximal score is the
# merge potential of 512,256,...,2: sum(v*(log2(v)-1)) = 7172.
MAX_SCORE=sum((1<<rank)*(rank-1) for rank in range(1,10))
LINES={
    'left':((0,1,2),(3,4,5),(6,7,8)),
    'right':((2,1,0),(5,4,3),(8,7,6)),
    'up':((0,3,6),(1,4,7),(2,5,8)),
    'down':((6,3,0),(7,4,1),(8,5,2)),
}

def validate_board(board):
    if len(board)!=9 or any(type(v) is not int or v<0 or (v and (v<2 or v&(v-1))) for v in board):
        raise ValueError('棋盘必须是9个空格或2的幂')
    return tuple(board)

@lru_cache(maxsize=32768)
def move_line(line):
    values=[v for v in line if v];out=[];score=0;i=0
    while i<len(values):
        value=values[i]
        if i+1<len(values) and value==values[i+1]:
            value*=2;score+=value;i+=1
        out.append(value);i+=1
    return tuple(out+[0]*(3-len(out))),score

@lru_cache(maxsize=65536)
def move(board,direction):
    result=list(board);score=0
    for indices in LINES[direction]:
        values,gain=move_line(tuple(board[i] for i in indices));score+=gain
        for i,v in zip(indices,values):result[i]=v
    return tuple(result),score

def legal_moves(board):
    return [(direction,*move(board,direction)) for direction in DIRECTIONS if move(board,direction)[0]!=board]

def board_score(board):
    """Exact score for this game's rules: every initial/spawned tile is 2.

    Merging two v tiles raises this potential by 2*v, exactly the awarded
    score. A newly spawned 2 contributes zero, so no score OCR is needed.
    """
    return sum(v*(v.bit_length()-2) for v in validate_board(board) if v)

@lru_cache(maxsize=32768)
def line_value(line):
    ranks=[v.bit_length()-1 if v else 0 for v in line]
    empty=ranks.count(0);filled=[r for r in ranks if r]
    merges=sum(a==b for a,b in zip(filled,filled[1:]))
    inc=sum(max(0,b**4-a**4) for a,b in zip(ranks,ranks[1:]))
    dec=sum(max(0,a**4-b**4) for a,b in zip(ranks,ranks[1:]))
    return 200000+270*empty+700*merges-47*min(inc,dec)-11*sum(r**3.5 for r in ranks)

def evaluate(board):
    return sum(line_value(tuple(board[i] for i in row)) for row in LINES['left']+LINES['up'])

def valid_transition(before,direction,after):
    """Exactly the selected slide and one new 2; no guessed or blind moves."""
    expected,_=move(before,direction)
    if expected==before:return False
    changed=[i for i in range(9) if expected[i]!=after[i]]
    return len(changed)==1 and expected[changed[0]]==0 and after[changed[0]]==2

def choose_move(board,max_depth=8,time_budget=.45,check_stop=lambda:None):
    board=validate_board(board);choices=legal_moves(board)
    if not choices:return None
    deadline=time.monotonic()+time_budget;nodes=0;cache={}
    class Deadline(Exception):pass
    def visit():
        nonlocal nodes
        nodes+=1
        if nodes%128==0:
            check_stop()
            if time.monotonic()>=deadline:raise Deadline()
    def player(state,depth):
        visit();key=(state,depth)
        if key in cache:return cache[key]
        moves=legal_moves(state)
        if not moves:return -10000000.0
        if depth==0:return evaluate(state)
        result=max(gain+chance(after,depth-1) for _,after,gain in moves)
        cache[key]=result;return result
    def chance(state,depth):
        spots=[i for i,v in enumerate(state) if not v]
        if not spots:return player(state,depth)
        value=0
        for i in spots:
            spawned=state[:i]+(2,)+state[i+1:]
            value+=player(spawned,depth)
        return value/len(spots)
    best=max(choices,key=lambda item:evaluate(item[1])+item[2])[0];completed=0
    for depth in range(1,max_depth+1):
        check_stop()
        try:values=[(gain+chance(after,depth-1),direction) for direction,after,gain in choices]
        except Deadline:break
        best=max(values,key=lambda item:item[0])[1];completed=depth
        if time.monotonic()>=deadline:break
    return {'direction':best,'depth':completed,'nodes':nodes}
