"""Manually opened 拼二 tool: score target and optional game cap."""
from datetime import datetime
import re
import numpy as np
from .backend import Backend
from .policy import TaskBlocked,SafetyStop,UserStopped
from .puzzle_solver import choose_move,legal_moves,valid_transition,board_score,move,MAX_SCORE
from .tool_settings import puzzle_options

CELLS=tuple((x,y) for y in (81,278,475) for x in (346,544,742))
SWIPES={'left':(820,375,450,375),'right':(450,375,820,375),
        'up':(640,550,640,200),'down':(640,200,640,550)}
NAMES={'left':'左','right':'右','up':'上','down':'下'}

def is_puzzle(s):
    return bool(s.find('^小游戏$',(90,0,180,65)) and
                s.find('^拼二大作战$',(35,450,220,80)) and
                s.find('^得分$',(590,0,100,35)))

def is_puzzle_settlement(s):
    return bool(s.find('^小游戏$',(90,0,180,65)) and
                s.find('^结算$',(535,125,220,100)) and
                s.find('^得分$',(540,265,200,80)) and
                s.find('^排行榜$',(1100,610,180,100)))

def terminal_after_move(before,direction):
    if before is None or direction is None:
        raise TaskBlocked('当前停在拼二结算页，请确认结算后从棋盘启动')
    after,_=move(before,direction);empty=[i for i,v in enumerate(after) if not v]
    if after==before or len(empty)!=1:raise TaskBlocked('拼二结算与刚才棋盘不符，未确认或重开')
    result=list(after);result[empty[0]]=2;result=tuple(result)
    if legal_moves(result):raise TaskBlocked('拼二结算时仍有合法方向，未确认或重开')
    return result

def read_board(b,s):
    b.guard(s)
    if not is_puzzle(s):raise TaskBlocked('请先在游戏中打开“丰野间 → 拼二大作战”的棋盘，再启动小工具')
    if s.find('^规则$|^确定$|^取消$|游戏结束|再来一次',roi=(280,160,720,430)):
        raise TaskBlocked('小游戏有弹窗，请先手动关闭后继续')
    board=[]
    for index,(x,y) in enumerate(CELLS):
        patch=s.image[y+8:y+180,x+8:x+180].astype('int16')
        empty=np.mean(np.max(np.abs(patch-np.array([66,48,24])),axis=2)<24)
        if empty>.96:board.append(0);continue
        if np.mean(patch.mean(axis=2)>100)<.3:
            raise TaskBlocked(f'第{index//3+1}行第{index%3+1}列尚未读清')
        value=b.read_number(s,(x+6,y+7,110,60))
        if value is None:
            local=b.read_text_region(s,(x+6,y+7,160,59),scale=2)
            if re.fullmatch(r'\d{1,5}',local):value=int(local)
        if value is None or value<2 or value>65536 or value&(value-1):
            raise TaskBlocked(f'第{index//3+1}行第{index%3+1}列数字未读清')
        board.append(value)
    if not any(board):raise TaskBlocked('棋盘仍在加载')
    return tuple(board)

class PuzzlePlayer:
    def __init__(self,b,report,emit=lambda *a:None):
        self.b=b;self.report=report;self.emit=emit;self.last_screen=None

    def stable_board(self,before=None,direction=None):
        prior=None;reason='棋盘未稳定'
        for _ in range(6):
            s=self.b.observe(self.report['folder']/'latest.png')
            # The standalone tool has no Daily observer, so share the same
            # lore-card handler without resetting its board or move history.
            from .story_cards import story_identity,close_story_card
            for _ in range(8):
                if story_identity(s) is None:break
                s=close_story_card(self.b,s,self.report,self.b.log,source_task='puzzle')
                self.b.save_screen(s,self.report['folder']/'latest.png')
            else:raise TaskBlocked('连续故事卡尚未关闭，保留当前拼二棋盘')
            self.last_screen=s
            self.emit('preview',str(self.report['folder']/'latest.png'))
            try:
                self.b.guard(s)
                board=terminal_after_move(before,direction) if is_puzzle_settlement(s) else read_board(self.b,s)
                accepted=before is None or valid_transition(before,direction,board)
                if accepted and board==prior:return s,board
                if not accepted:reason='滑动后棋盘与预期合并不符，未继续输入'
                prior=board if accepted else None
            except TaskBlocked as e:
                if not is_puzzle(s) and before is None:raise
                reason=str(e);prior=None
            self.b.sleep(.25)
        raise TaskBlocked(reason)

    def restart(self,s):
        self.b.guard(s)
        if is_puzzle_settlement(s):
            self.b.save_screen(s,self.report['folder']/f'puzzle-settlement-{self.report.get("game",1)}.png')
            self.b.click_at(s,(640,570),['^小游戏$','^结算$','^得分$','^排行榜$'],'确认拼二结算')
        else:
            if not is_puzzle(s) or not s.find('^重开$',(70,580,150,120)):
                raise TaskBlocked('拼二重开按钮未确认')
            self.b.click_text(s,'^重开$',(70,580,150,120))
        s,board=self.stable_board()
        if sum(board)!=2 or board_score(board)!=0:
            raise TaskBlocked('未确认新局已经开始，不重复点击重开')
        return s,board

    def play(self,target_score=MAX_SCORE,max_games=0,*,finish_round=False):
        target,max_games=puzzle_options({'puzzle_target_score':target_score,'puzzle_max_games':max_games})
        s,board=self.stable_board();steps=0;game=1;game_steps=0;best=0
        self.b.log(f'拼二目标{target}分，'+(f'最多{max_games}局' if max_games else '局数不限，未达目标则输后重开'))
        while True:
            self.b.check_stop();score=board_score(board)
            if score>MAX_SCORE:raise TaskBlocked('识别出的棋盘得分超过7172，停止并保留现场')
            best=max(best,score)
            self.report.update(moves=steps,board=list(board),score=score,
                               score_source='verified_moves' if is_puzzle_settlement(s) else 'verified_board',
                               max_tile=max(board),game=game,target_score=target,max_games=max_games,best_score=best)
            self.emit('puzzle',{'board':board,'score':score,'moves':steps,'max_tile':max(board),'game':game})
            terminal=not legal_moves(board)
            if score>=target and (not finish_round or terminal):
                self.report['goal_reached']=True
                self.report.setdefault('games',[]).append({'game':game,'score':score,'moves':game_steps,'outcome':'target_reached'})
                return f'第{game}局已达{score}分，完成{target}分目标，'+('已完成本局结算' if finish_round else '保留当前棋盘')
            if terminal:
                self.report.setdefault('games',[]).append({'game':game,'score':score,'moves':game_steps,'outcome':'ended'})
                if max_games and game>=max_games:
                    self.report['goal_reached']=False
                    return f'已达{max_games}局上限，{target}分目标尚未达成；本轮最高分{best}'
                self.b.log(f'第{game}局结束，得分{score}，未达{target}分；自动重开')
                s,board=self.restart(s);game+=1;game_steps=0
                self.b.log(f'开始第{game}局'+(f'（最多{max_games}局）' if max_games else '（局数不限）'));continue
            # The daily ladder only credits a finished round. Once its small
            # target is reached, finish the board instead of pursuing a rank.
            if finish_round and score>=target:
                direction=min(legal_moves(board),key=lambda row:(row[1].count(0),row[2]))[0]
                choice={'direction':direction,'depth':0}
            else:choice=choose_move(board,check_stop=self.b.check_stop)
            direction=choice['direction']
            self.b.check_stop();self.b.guard(s)
            if not is_puzzle(s):raise TaskBlocked('已离开拼二棋盘，停止输入')
            self.b.log(f'拼二第{game}局第{game_steps+1}步：向{NAMES[direction]}；得分{score}')
            self.emit('phase',f'拼二第{game}局'+(f'/{max_games}局' if max_games else '（局数不限）')+f' · 目标{target}分 · 第{game_steps+1}步 · 向{NAMES[direction]}')
            action={'action':'swipe','reason':'拼二第'+str(steps+1)+'步','direction':direction,
                    'board':list(board),'search_depth':choice['depth'],'status':'requested'}
            self.b.audit(action)
            self.b.guard(s)
            if not self.b.wait(self.b.controller.post_swipe(*SWIPES[direction],350)).succeeded:
                raise SafetyStop('拼二滑动发送失败，保留棋盘')
            self.b.audit({**action,'status':'sent'})
            self.b.sleep(.3);s,board=self.stable_board(board,direction);steps+=1;game_steps+=1

LEAF_ROIS=((1115,60,90,85),(1015,180,75,65),(1170,268,75,65),
           (1015,335,75,65),(1170,445,75,65))

def daily_leaves_claimed(s):
    return is_puzzle(s) and all(s.find('^已领取$',roi) for roi in LEAF_ROIS)

def puzzle_daily_best(b,s,confirmed_score=None,*,visual_candidate=False):
    if not is_puzzle(s):return None
    roi=(1028,573,80,32)
    value=b.read_number(s,roi)
    if value is not None:return value if 0<=value<=MAX_SCORE else None
    # Outlined zero is often "o", while recognition-only OCR returns nothing.
    # Full-frame and enlarged local detection must agree; unknown isn't zero.
    word=s.find(r'^[0-9Oo]+$',roi)
    local=b.read_text_region(s,roi,scale=2).translate(str.maketrans('Oo','00')).strip()
    if word and re.fullmatch(r'\d+',local):
        full=word.text.translate(str.maketrans('Oo','00'))
        if int(full)==int(local) and 0<=int(local)<=MAX_SCORE:return int(local)
    # The glowing three-digit score is visible to full-frame OCR but may
    # disappear entirely from cropped OCR. Only trust that lower-confidence
    # word when a just-finished, locally verified game corroborates it.
    if confirmed_score is not None and confirmed_score>=300 and s.find('^今日最高$',(1000,525,140,55)):
        word=s.find(r'^\d{3,4}$',roi)
        if word and word.score>=.60:
            value=int(word.text)
            if value==confirmed_score or (value>confirmed_score and word.score>=.80):
                if value<=MAX_SCORE:return value
    if visual_candidate and s.find('^今日最高$',(1000,525,140,55)) and s.find('^300$',(1110,125,95,52)):
        word=s.find(r'^\d{3,4}$',roi)
        if word and word.score>=.60 and 0<=int(word.text)<=MAX_SCORE:
            return int(word.text)
    return None


def await_daily_best(d,s,confirmed_score=None):
    visual_previous=None
    for retry in range(4):
        d.b.guard(s)
        value=puzzle_daily_best(d.b,s,confirmed_score)
        if value is not None:return s,value
        visual=puzzle_daily_best(d.b,s,visual_candidate=True)
        if visual is not None and visual==visual_previous:
            return s,visual
        visual_previous=visual
        if retry<3:
            d.note(f'拼二今日最高分未读清，重新识别（{retry+1}/3）')
            d.b.sleep(.6);s=d.observe()
    return s,None

def puzzle_daily(d):
    """Daily 300 points, including finishing the round and server-side rewards."""
    s=d.observe();d.b.guard(s)
    if not is_puzzle(s) and not is_puzzle_settlement(s):
        from .event_hub import event_hub_anchors,activity_entry,activity_availability
        s=d.event_hub(s)
        w=activity_entry(s,'puzzle')
        if not w:return {'status':'skipped','message':'丰野间当前没有拼二大作战入口，已跳过'}
        availability=activity_availability(s,w)
        if availability=='ended':return {'status':'skipped','message':'拼二大作战活动已结束，已跳过'}
        if availability=='not_open':return {'status':'skipped','message':'拼二大作战尚未开放，已跳过'}
        d.b.click_at(s,w.center,event_hub_anchors(s),'进入拼二每日任务')
        s=d.await_page('^小游戏$','^得分$','^拼二大作战$')
    if is_puzzle_settlement(s):
        d.b.click_at(s,(640,570),['^小游戏$','^结算$','^得分$'],'确认已有拼二结算')
        s=d.await_page('^小游戏$','^得分$','^拼二大作战$')
    if daily_leaves_claimed(s):return {'status':'done','message':'拼二今日300分树叶奖励已全部领取，跳过'}
    s,best=await_daily_best(d,s)
    if best is None:raise TaskBlocked('拼二今日最高分未读清，保留当前棋盘')
    record=d.report.setdefault('daily_puzzle',{})
    if best<300:
        play_record={'folder':d.report['folder']}
        player=PuzzlePlayer(d.b,play_record,d.emit)
        d.note('拼二每日任务：达到300分后完成本局结算，再领右侧树叶')
        try:d.note(player.play(300,0,finish_round=True))
        finally:
            d.last_screen=player.last_screen or s
            record.update({k:v for k,v in play_record.items() if k!='folder'})
        s=player.last_screen
        if not is_puzzle_settlement(s):raise TaskBlocked('拼二达到目标但尚未出现结算，不记为每日完成')
        d.b.click_at(s,(640,570),['^小游戏$','^结算$','^得分$'],'确认拼二每日成绩')
        s=d.await_page('^小游戏$','^得分$','^拼二大作战$')
        s,best=await_daily_best(d,s,record.get('score'))
        if best is None or best<300:raise TaskBlocked('拼二结算后今日最高分未确认达到300')
    if not daily_leaves_claimed(s):
        d.b.click_at(s,(1158,102),['^小游戏$','^得分$','^300$'],'领取右侧拼二树叶奖励')
        reward=d.await_page('^获得奖励$','点击空白位置关闭')
        d.b.save_screen(reward,d.report['folder']/'daily-puzzle-reward.png')
        record['reward_text']=reward.text
        tokens=reward.find(r'^\d+$',(615,345,105,70))
        if tokens:record['claimed_tokens']=int(tokens.text)
        d.b.click_at(reward,(640,660),['^获得奖励$','点击空白位置关闭'],'关闭拼二树叶奖励')
        s=d.await_page('^小游戏$','^得分$','^拼二大作战$')
        if not daily_leaves_claimed(s):raise TaskBlocked('拼二树叶奖励尚未全部确认已领取，未重复点击')
    record.pop('folder',None);record['claimed']=True;record['daily_best']=best
    amount=record.get('claimed_tokens')
    detail=f'，本次到账{amount}活动代币' if amount is not None else ''
    return {'status':'done','message':f'拼二今日最高{best}分，右上300分档150代币及低档奖励已领取{detail}'}

def run_puzzle(settings,stop,log=print,emit=lambda *a:None):
    from .workflows import create_report,write_report
    report=create_report();report['tool']='puzzle';report['diamond_spend']=0
    def audit(action):
        import json
        with (report['folder']/'actions.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'time':datetime.now().astimezone().isoformat(),**action},ensure_ascii=False)+'\n')
    def note(message):
        log(message);report['events'].append({'time':datetime.now().isoformat(timespec='seconds'),'message':message})
    b=Backend(settings,stop,note,lambda message:emit('phase',message),audit);player=PuzzlePlayer(b,report,emit)
    try:
        target,games=puzzle_options(settings)
        b.connect();report['reason']=player.play(target,games)
        report['status']='partial' if report.get('goal_reached') is False else 'completed';note(report['reason'])
    except UserStopped as e:report.update(status='stopped',reason=str(e))
    except Exception as e:report.update(status='blocked',reason=str(e));note('已停止：'+str(e))
    finally:
        if player.last_screen is not None:b.save_screen(player.last_screen,report['folder']/'puzzle-final.png')
        report['finished']=datetime.now().astimezone().isoformat();write_report(report)
    return report
