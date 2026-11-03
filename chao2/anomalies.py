"""Anomaly children: copy encounters and the wandering sage's observed quiz flow."""
import json
import re
import time
from functools import lru_cache

import numpy as np
from PIL import Image

from .backend import ROOT,Word
from .policy import TaskBlocked,EncounterInterrupted
from .trigger_events import event_enabled,require_event_enabled


def is_sage_offer(s):
    return bool(s.find('^游荡智者$', (320,100,220,85)) and
                s.find('^前往$', (540,530,200,90)))


def is_sage_dialog(s):
    return bool(s.find('^游荡智者$', (0,0,290,85)) and
                s.find('^游荡智者$', (70,470,300,80)))


def is_event_panel(s):
    return bool(s.find('^战斗$',(1200,95,80,70)) and
                s.find('^狩猎$',(1200,200,80,80)) and
                s.find('^传送$',(1200,315,80,80)) and
                not s.find('^获得|^请选择$|^奖励$|^主要获得途径$|种族限定'))


@lru_cache(maxsize=1)
def instant_frame():
    im=np.array(Image.open(ROOT/'resource/image/instant-off.png').convert('RGB'))[:,:,::-1]
    mask=np.ones(im.shape[:2],bool)
    mask[5:-5,5:-5]=False  # Both checked and unchecked boxes have this same rim.
    return im.astype('int16'),mask


def instant_checkbox_present(s):
    template,mask=instant_frame();h,w=template.shape[:2]
    crop=s.image[680:720,1000:1055].astype('int16')
    rim=template[mask].astype('float32');rim-=rim.mean(axis=0)
    energy=np.square(rim).sum()
    for y in range(crop.shape[0]-h+1):
        for x in range(crop.shape[1]-w+1):
            pixels=crop[y:y+h,x:x+w][mask]
            if np.abs(pixels-template[mask]).mean()>=18:continue
            # A dark piece of map scenery can share the rim's average color.
            # Require the rounded border's spatial pattern too; ignore the
            # center so a checked box still counts as present and stays blocked.
            centered=pixels.astype('float32');centered-=centered.mean(axis=0)
            denominator=np.sqrt(energy*np.square(centered).sum())
            if denominator>0 and (centered*rim).sum()/denominator>=.8:return True
    return False


def evolved_copy_without_instant(s):
    # This is a distinct, captured layout. An unreadable ordinary checkbox
    # must never be treated as an absent checkbox merely because OCR missed it.
    # Full-frame OCR often drops the small tier numeral inside 暴进Ⅱ (it reads
    # 【暴进】), so the numeral is optional; the banner prefix plus the three
    # layout anchors below are the actual evidence.
    # The gold left bracket also reads as '(' on the captured tier-I banner.
    return bool(s.find(r'^[【\[(（]\s*暴进\s*[ⅠⅡⅢⅣⅤIVX1-9ILl|]*\s*[】\]]', (125,125,390,45)) and
                s.has('^敌方阵容$','^排阵$','^前往挑战$') and
                s.find('^20$', (1060,630,90,45)) and
                not s.find('瞬破') and not instant_checkbox_present(s))


def normalize_answer(text):
    return re.sub(r'[^\w\u4e00-\u9fff]','',text).lower()


def sage_question(s):
    if not is_sage_dialog(s):return ''
    words=sorted((w for w in s.words if 85<=w.center[0]<1170 and 545<=w.center[1]<602),
                 key=lambda w:(w.box[1]//20,w.box[0]))
    return ''.join(w.text for w in words).strip()


def sage_choices(s):
    if not is_sage_dialog(s) or not s.find('^请选择$', (650,0,500,75)):return []
    words=sorted((w for w in s.words if 600<=w.center[0]<1160 and 80<=w.center[1]<455),
                 key=lambda w:(w.center[1],w.box[0]))
    rows=[]
    for w in words:
        if rows and abs(rows[-1][0].center[1]-w.center[1])<22:rows[-1].append(w)
        else:rows.append([w])
    # OCR can split the joke/hint from the answer on the same button.
    result=[]
    for row in rows:
        row.sort(key=lambda w:w.box[0])
        x=min(w.box[0] for w in row);y=min(w.box[1] for w in row)
        right=max(w.box[0]+w.box[2] for w in row);bottom=max(w.box[1]+w.box[3] for w in row)
        result.append(Word(''.join(w.text for w in row),[x,y,right-x,bottom-y],min(w.score for w in row)))
    return result


def sage_answer(s,bank=None):
    """Exact normalized question + unique visible option, never fuzzy guessing."""
    if bank is None:
        bank=json.loads((ROOT/'resource/sage-answers.json').read_text('utf-8'))['questions']
    question=normalize_answer(sage_question(s))
    entries=[row for row in bank if question in {normalize_answer(q) for q in row['questions']}]
    answers={normalize_answer(a) for row in entries for a in row['answers']}
    matches=[w for w in sage_choices(s) if normalize_answer(w.text) in answers]
    return matches[0] if len(matches)==1 else None


def sage_verdict(s):
    if not is_sage_dialog(s):return None
    if s.find('答对了', (85,595,600,60)):return 'correct'
    if s.find('答错|不对|回答错误', (85,595,600,60)):return 'incorrect'
    return None


def sage_phase(s):
    """Stable controls, not the varying portrait or background animation."""
    from .workflows import is_world
    if s.find('^获得奖励$',(400,75,500,150)):return ('reward',)
    if is_world(s):return ('world',)
    if not is_sage_dialog(s):return ('unknown',)
    verdict=sage_verdict(s)
    if verdict:return ('verdict',verdict,normalize_answer(sage_question(s)))
    if s.find('^请选择$',(650,0,500,75)):
        return ('choices',normalize_answer(sage_question(s)),
                tuple(normalize_answer(w.text) for w in sage_choices(s)))
    text=normalize_answer(s.region_text((85,545,1090,110)))
    return ('dialog',text) if text else ('unknown',)


class AnomalyActivities:
    def open_world_events(self,s):
        from .activities import is_copy_list
        from .workflows import is_world,is_tasks
        if is_event_panel(s) or is_copy_list(s):return s
        self.click_world(s,(1105,620),'从世界事件进入异象')
        until=time.monotonic()+18;retry_at=time.monotonic()+3;retried=False
        while time.monotonic()<until:
            q=self.observe();self.b.guard(q)
            self.resolve_path_event(q)
            if is_event_panel(q) or is_copy_list(q):return q
            if not retried and is_tasks(q):
                # Returning from an overview-launched dungeon can briefly show
                # the map before restoring the overview. Close that known panel
                # and retry navigation; it says nothing about wild availability.
                self.note('返回副本后概览面板重新出现，关闭后再打开事件')
                q=self.home(q)
                self.click_world(q,(1105,646),'返回世界后打开事件')
                retried=True
                until=time.monotonic()+18
                continue
            # Recover only a navigation click on a freshly confirmed map.
            # No combat, claim or payment input is ever replayed here.
            if not retried and time.monotonic()>=retry_at and is_world(q):
                self.b.save_screen(q,self.report['folder']/'event-open-unconfirmed.png')
                self.note('事件入口尚未打开，确认仍在世界后重试一次')
                self.click_world(q,(1105,646),'重试打开世界事件')
                retried=True
            self.b.sleep(.6)
        self.b.save_screen(q,self.report['folder']/'event-open-unconfirmed.png')
        raise TaskBlocked('事件列表未打开，已停止重试；尚未检查到列表内容')

    def open_anomaly_list(self,s):
        from .activities import is_copy_list,COPY_LIST_ANCHORS
        if self.overview_prepared_for('copies'):
            return self.enter_overview('^异象$')
        if not is_event_panel(s):
            s=self.home(s)
            s=self.open_world_events(s)
        if is_copy_list(s):return s
        if not s.find('^异象$',(810,650,120,60)):
            self.b.click_text(s,'^战斗$',roi=(1200,95,80,70))
            s=self.sage_wait(lambda q:is_copy_list(q) or (is_event_panel(q) and q.find('^异象$',(810,650,120,60))),
                             '事件中的战斗分类未打开')
        if is_copy_list(s):return s
        self.b.click_text(s,'^异象$',roi=(810,650,120,60))
        return self.await_page(*COPY_LIST_ANCHORS)

    def copies(self):
        from .activities import BudgetReached
        options=self.options['copies'];results=self.report.setdefault('anomaly_tasks',{})
        messages=[];blocked=[]
        for key,label,enabled,run in (
                ('copies','复制体',options['challenge_copies'],self.copy_battles),
                ('sage','游荡智者',options['wandering_sage'] and event_enabled(self.b.settings,'sage_quiz'),self.wandering_sage)):
            if not enabled:
                if key=='copies':self.stamina_retry['copies']=False
                results[key]={'status':'disabled','message':'未勾选'}
                continue
            if key=='sage' and results.get(key,{}).get('status')=='done':
                messages.append('游荡智者本轮已检查');continue
            self.note('异象 · '+label)
            try:
                message=run();status='done'
            except BudgetReached as e:
                message=str(e);status='done'
                if key=='copies':self.stamina_retry['copies']='体力不足' in message
            except EncounterInterrupted:raise
            except TaskBlocked as e:
                message=str(e);status='blocked';blocked.append(label+'：'+message)
                if hasattr(self,'last_screen'):
                    self.b.save_screen(self.last_screen,self.report['folder']/('anomaly-'+key+'-blocked.png'))
            results[key]={'status':status,'message':message}
            messages.append(message);self.note(label+'：'+message);self.checkpoint()
        if blocked:raise TaskBlocked('；'.join(blocked))
        return '；'.join(messages) if messages else '复制体与游荡智者均未勾选'

    def sage_wait(self,predicate,message,timeout=18):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            s=self.observe();self.b.guard(s)
            self.resolve_path_event(s)
            if predicate(s):return s
            self.b.sleep(.6)
        raise TaskBlocked(message)

    def resume_sage_dialog(self,s):
        """Resume an encountered quiz independently of the scheduled task list."""
        if not is_sage_dialog(s) or getattr(self,'_sage_active',False):return None
        require_event_enabled(self.b.settings,'sage_quiz')
        # A recovery must not resubmit an unknown or already submitted answer.
        # A completed quiz is checked once per run, just like the anomaly task.
        if self.report.get('sage_quiz'):return None
        self.note('检测到未结束的游荡智者对话，先接续答题与免费领奖')
        message=self.wandering_sage(entry=s)
        self.report.setdefault('anomaly_tasks',{})['sage']={'status':'done','message':message,'resumed':True}
        self.note(message);self.checkpoint()
        return self.observe()

    def wandering_sage(self,*,entry=None):
        require_event_enabled(self.b.settings,'sage_quiz')
        self._sage_active=True
        try:return self._play_wandering_sage(entry=entry)
        finally:self._sage_active=False

    def _play_wandering_sage(self,*,entry=None):
        from .workflows import is_world
        from .activities import COPY_LIST_ANCHORS
        s=entry if entry is not None else self.observe();self.b.guard(s)
        before=self.world_resources(s) if is_world(s) else None
        if not is_sage_offer(s) and not is_sage_dialog(s):
            s=self.copy_first_page(self.copy_list())
            entry=s.find('^游荡智者$', (890,175,310,455))
            if not entry:
                self.home()
                return '当前异象列表没有游荡智者，跳过'
            self.b.click_at(s,entry.center,list(COPY_LIST_ANCHORS),'打开游荡智者')
            s=self.sage_wait(lambda q:is_sage_offer(q) or is_sage_dialog(q),
                             '游荡智者详情未打开')
        if is_sage_offer(s):
            self.b.click_text(s,'^前往$',roi=(540,530,200,90))
            # The client walks to the NPC. Do not repeatedly open the event.
            s=self.sage_wait(is_sage_dialog,'前往游荡智者后未进入对话',timeout=40)
        if self.options['copies']['sage_until_end']:
            return self.sage_until_finished(s,before)
        row=self.report.setdefault('sage_quiz',{})
        if not sage_choices(s) and not sage_verdict(s) and not s.find('^获得奖励$'):
            if not sage_question(s):raise TaskBlocked('游荡智者题目未读清，保留对话')
            self.b.click_at(s,(1152,652),['^游荡智者$'],'展开智者答题选项')
            s=self.sage_wait(lambda q:bool(sage_choices(q)) or sage_verdict(q),
                             '游荡智者选项未出现，保留对话')
        if not sage_verdict(s) and not s.find('^获得奖励$'):
            question=sage_question(s);choices=sage_choices(s)
            row.update(question=question,choices=[w.text for w in choices])
            self.b.save_screen(s,self.report['folder']/'sage-question.png')
            answer=sage_answer(s)
            if answer is None:
                row['status']='unknown_answer';self.checkpoint()
                raise TaskBlocked('游荡智者题库尚未收录或选项未读清：'+question+'；已保存题目，未乱选')
            row.update(answer=answer.text,status='answering');self.checkpoint()
            self.note('游荡智者：'+question+' → '+answer.text)
            self.b.click_at(s,answer.center,['^游荡智者$','^请选择$','^'+re.escape(answer.text)+'$'],
                            '回答游荡智者')
            s=self.sage_wait(lambda q:sage_verdict(q) is not None,
                             '已提交智者答案，尚未识别答题结果；未重复提交')
        verdict=sage_verdict(s)
        if verdict:
            row.update(status=verdict);self.checkpoint()
            self.b.save_screen(s,self.report['folder']/'sage-result.png')
            if verdict!='correct':raise TaskBlocked('游荡智者提示答错，保留结果供检查，未重复选择')
            self.b.click_at(s,(1152,652),['^游荡智者$','答对了'],'领取智者答题奖励')
            s=self.sage_wait(lambda q:bool(q.find('^获得奖励$', (400,75,500,150))),
                             '智者答对但奖励尚未出现，未计为已领奖')
        if not s.find('^获得奖励$', (400,75,500,150)):
            raise TaskBlocked('游荡智者奖励未确认')
        self.b.save_screen(s,self.report['folder']/'sage-reward.png')
        row['reward_observed']=True
        self.b.click_at(s,(640,665),['^获得奖励$','点击空白位置关闭'],'关闭智者奖励')
        s=self.sage_wait(is_world,'智者奖励已显示，尚未返回世界地图')
        after=self.world_resources(s);row.update(status='done',resources_after=after)
        suffix=''
        if before:
            row['resources_before']=before
            if before.get('diamonds') is not None and after.get('diamonds') is not None:
                row['diamond_change']=after['diamonds']-before['diamonds']
                if row['diamond_change']>0:suffix=f'，钻石增加{row["diamond_change"]}'
        self.checkpoint()
        return '游荡智者答对，奖励已领取'+suffix

    def sage_until_finished(self,s,before=None):
        """Advance this encounter until reward closure and a real world return."""
        row=self.report.setdefault('sage_quiz',{})
        if before:row['resources_before']=before
        row['continuous']=True
        while True:
            self.b.guard(s)
            phase=sage_phase(s)
            if phase[0]=='world':
                after=self.world_resources(s);row['resources_after']=after
                if before and before.get('diamonds') is not None and after.get('diamonds') is not None:
                    row['diamond_change']=after['diamonds']-before['diamonds']
                if not row.get('reward_observed'):
                    row['status']='ended_without_reward';self.checkpoint()
                    raise TaskBlocked('智者对话已结束，但未观察到奖励，未计为已领奖')
                row.pop('pending_answer',None)
                row['status']='done';self.checkpoint()
                return '游荡智者对话已结束，奖励已领取'
            if phase[0]=='reward':
                self.b.save_screen(s,self.report['folder']/'sage-reward.png')
                row.update(reward_observed=True,status='claiming');self.checkpoint()
                self.b.click_at(s,(640,665),['^获得奖励$','点击空白位置关闭'],'关闭智者奖励')
                # A reward can be followed by another line of dialogue.
                s=self.sage_wait(lambda q:sage_phase(q)[0] in ('world','dialog','verdict','choices'),
                                 '智者奖励已显示，关闭后页面尚未确认')
                row['rewards_closed']=row.get('rewards_closed',0)+1
                continue
            if phase[0]=='choices':
                choices=sage_choices(s);question=sage_question(s)
                if not question or not 2<=len(choices)<=4:
                    s=self.wait_for_screen(
                        lambda q:sage_phase(q)[0]=='choices' and bool(sage_question(q)) and 2<=len(sage_choices(q))<=4,
                        '读取智者题目与选项',timeout=3)
                    continue
                answered={normalize_answer(a['question']) for a in row.get('answers',[])}
                if normalize_answer(question) in answered:
                    raise TaskBlocked('智者答案已提交，结果尚未确认；未重复选择')
                answer=sage_answer(s);source='题库'
                if answer is None:
                    answer=next((w for w in choices if '选我' in w.text and '奖励' in w.text),choices[0])
                    source='持续完成'
                row.update(question=question,choices=[w.text for w in choices],
                           answer=answer.text,status='answering',
                           pending_answer={'question':normalize_answer(question),'answer':answer.text})
                row.setdefault('answers',[]).append({'question':question,'answer':answer.text,'source':source})
                self.b.save_screen(s,self.report['folder']/'sage-question.png')
                self.checkpoint();self.note(f'游荡智者（{source}）：{question} → {answer.text}')
                # A merged OCR row is not an individual OCR anchor. The title,
                # choice header and question identify the current free quiz.
                self.b.click_at(s,answer.center,['^游荡智者$','^请选择$'],'回答游荡智者')
                s=self.sage_wait(lambda q:sage_phase(q)[0] in ('reward','world','dialog','verdict') or
                                 (sage_phase(q)[0]=='choices' and bool(sage_question(q)) and
                                  normalize_answer(sage_question(q))!=normalize_answer(question)),
                                 '智者答案已提交，结果尚未确认；未重复选择')
                continue
            if phase[0] in ('dialog','verdict'):
                verdict=sage_verdict(s)
                if verdict:
                    row.setdefault('verdicts',[]).append(verdict)
                    self.b.save_screen(s,self.report['folder']/'sage-result.png')
                    self.note('游荡智者答'+('对' if verdict=='correct' else '错')+'，继续对话领取奖励')
                row['status']='dialog';self.checkpoint()
                def advance(q):
                    if sage_phase(q)==phase:
                        self.b.click_at(q,(1152,652),['^游荡智者$'],'继续智者对话')
                advance(s)
                s=self.wait_for_screen(lambda q:sage_phase(q)[0]!='unknown' and sage_phase(q)!=phase,
                                       '智者对话继续',timeout=4,retry_navigation=advance)
                continue
            s=self.wait_for_screen(lambda q:sage_phase(q)[0]!='unknown','识别智者后续页面',timeout=3)
