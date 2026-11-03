from __future__ import annotations
import io
import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import numpy as np
from PIL import Image
from maa.controller import CustomController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from maa.pipeline import JOCR,JTemplateMatch
from .policy import SafetyStop, PageChanged, UserStopped, TaskBlocked, dangerous_dialog, parse_ratio,is_stamina_potion_dialog

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'com.leiting.chaojinhua.jh.yxj'
ACTIVITY = PACKAGE + '/org.cocos2dx.javascript.AppActivity'
DEFAULT_ADB = 'D:/Program Files/Netease/MuMu/nx_main/adb.exe'
NO_WINDOW = subprocess.CREATE_NO_WINDOW

@dataclass
class Word:
    text: str
    box: list[int]
    score: float
    @property
    def center(self):
        x,y,w,h = self.box
        return x+w//2, y+h//2

@dataclass
class Screen:
    image: np.ndarray
    words: list[Word]
    when: float
    @property
    def text(self): return '\n'.join(w.text for w in self.words)
    def find(self, pattern, roi=None):
        matches = [w for w in self.words if re.search(pattern,w.text) and (roi is None or (roi[0] <= w.center[0] < roi[0]+roi[2] and roi[1] <= w.center[1] < roi[1]+roi[3]))]
        return max(matches, key=lambda w:w.score, default=None)
    def has(self,*patterns): return all(self.find(p) is not None for p in patterns)
    def region_text(self, roi):
        return ' '.join(w.text for w in self.words if roi[0] <= w.center[0] < roi[0]+roi[2] and roi[1] <= w.center[1] < roi[1]+roi[3])

def display_blocks(text):
    """MuMu runs each game on a separate Android display; never use global focus."""
    return [(int(m[1]),m[2]) for m in re.finditer(r'Display:\s*mDisplayId=(\d+)(.*?)(?=\n\s*Display:\s*mDisplayId=|\Z)',text,re.S)]

class MuMuController(CustomController):
    def __init__(self, adb, address, stop):
        self.adb, self.address, self.stop = str(adb), address, stop
        self.logical = None
        self.physical = None
        self.last_error = ''
        self.ready = False
        self.display_reconnected = None
        super().__init__()
    def cmd(self,*args,timeout=12,raw=False):
        result = subprocess.run([self.adb,'-s',self.address,*map(str,args)],capture_output=True,timeout=timeout,creationflags=NO_WINDOW)
        if result.returncode: raise SafetyStop(result.stderr.decode('utf-8','replace').strip() or 'ADB 失败')
        return result.stdout if raw else result.stdout.decode('utf-8','replace')
    def discover(self):
        blocks=display_blocks(self.cmd('shell','dumpsys','window','displays'))
        found=[]
        for display,block in blocks:
            focus = '\n'.join(line for line in block.splitlines() if 'mFocusedApp=' in line or 'mCurrentFocus=' in line)
            if PACKAGE+'/' in focus: found.append(display)
        if len(found) != 1: raise SafetyStop('未找到唯一的超二游戏屏幕。请先打开超二并停在游戏内。')
        logical=found[0]
        display_info=self.cmd('shell','dumpsys','display')
        ids=[m[2] for m in re.finditer(r'DisplayViewport\{[^}]*?displayId=(\d+), uniqueId=\x27local:(\d+)\x27',display_info) if int(m[1])==logical]
        if len(ids)!=1: raise SafetyStop('无法核对 MuMu 屏幕编号，停止连接')
        self.logical,self.physical=logical,ids[0]
    def verify(self):
        if self.stop.is_set(): raise UserStopped('已停止')
        block=dict(display_blocks(self.cmd('shell','dumpsys','window','displays'))).get(self.logical,'')
        focus='\n'.join(line for line in block.splitlines() if 'mFocusedApp=' in line or 'mCurrentFocus=' in line)
        if PACKAGE+'/' not in focus: raise SafetyStop('超二屏幕已关闭或切换，停止输入')
    def connect(self):
        try:
            subprocess.run([self.adb,'connect',self.address],capture_output=True,timeout=8,creationflags=NO_WINDOW)
            self.discover();self.ready=True;return True
        except Exception as e: self.last_error=str(e);return False
    def connected(self):return self.ready
    def request_uuid(self):return f'chao2:{self.address}:{self.logical}'
    def get_features(self):return 0
    def start_app(self,intent):return False  # launcher is a separate explicit user action
    def stop_app(self,intent):return False
    def screencap(self):
        try:
            try:self.verify()
            except SafetyStop:
                if self.stop.is_set():raise
                # MuMu can recreate the game's Android display during loading.
                # Rebind only while taking a fresh screenshot, on this same
                # device and only to one uniquely identified game surface.
                previous=self.logical;self.discover();self.verify()
                if previous!=self.logical:self.display_reconnected=(previous,self.logical)
            b=self.cmd('exec-out','screencap','-p','-d',self.physical,raw=True)
            a=np.array(Image.open(io.BytesIO(b)).convert('RGB'))[:,:,::-1].copy()
            if a.shape[1]/a.shape[0] < 1.7: raise SafetyStop('游戏方向或分辨率异常')
            return a
        except Exception as e:self.last_error=str(e);return np.zeros((0,0,3),dtype=np.uint8)
    def click(self,x,y):
        try:self.verify();self.cmd('shell','input','-d',self.logical,'tap',x,y);return True
        except Exception as e:self.last_error=str(e);return False
    def swipe(self,x1,y1,x2,y2,duration):
        self.last_error=''
        try:self.verify();self.cmd('shell','input','-d',self.logical,'swipe',x1,y1,x2,y2,duration);return True
        except Exception as e:self.last_error=str(e);return False
    def click_key(self,keycode): return False
    def input_text(self,text): return False
    def key_down(self,keycode):return False
    def key_up(self,keycode):return False
    def touch_down(self,*args):return False
    def touch_move(self,*args):return False
    def touch_up(self,*args):return False
    def get_custom_info(self):return {'package':PACKAGE,'display':self.logical,'physical':self.physical}

class Backend:
    def __init__(self, settings, stop=None, log:Callable=print, progress:Callable=lambda _:None, audit:Callable=lambda _:None):
        self.stop=stop or threading.Event();self.log=log;self.settings=settings
        self.progress=progress;self.audit=audit
        self.controller=None;self.tasker=None;self.resource=None
    def stage(self,message):
        self.log(message);self.progress(message)
    def back(self,s,reason):
        from .page_recovery import visual_return_control
        self.guard(s)
        control=visual_return_control(s)
        if control is None:raise TaskBlocked('当前画面未确认返回箭头或关闭按钮，未猜测点击')
        verified=Screen(s.image,[*s.words,control],s.when)
        self.click_at(verified,control.center,['^'+re.escape(control.text)+'$'],reason)
    def connect(self):
        self.check_stop()
        self.stage('正在连接 MuMu · '+self.settings.get('address','127.0.0.1:16384'))
        Toolkit.init_option(ROOT, {'logging':True,'stdout_level':2,'save_draw':False})
        self.controller=MuMuController(self.settings.get('adb',DEFAULT_ADB),self.settings.get('address','127.0.0.1:16384'),self.stop)
        if not self.wait(self.controller.post_connection(),25).succeeded:
            raise SafetyStop(self.controller.last_error or 'MuMu 连接失败')
        self.stage('已找到超二屏幕，正在加载识图资源')
        self.controller.set_screenshot_target_long_side(1280)
        self.resource=Resource()
        if not self.wait(self.resource.post_bundle(ROOT/'resource'),20).succeeded:raise SafetyStop('MaaFramework 资源加载失败')
        self.tasker=Tasker()
        if not self.tasker.bind(self.resource,self.controller) or not self.tasker.inited:raise SafetyStop('MaaFramework 初始化失败')
        self.log(f'连接成功 · 超二屏幕 {self.controller.logical} · MaaFramework 5.14.3')
        self.progress('连接成功，正在读取游戏画面')
    def wait(self,job,timeout=15):
        until=time.monotonic()+timeout
        while not job.done:
            if self.stop.wait(.05):
                self.stop_pending(job)
                raise UserStopped('用户停止')
            if time.monotonic()>until:
                self.stop_pending(job)
                raise SafetyStop('操作超时，已中止')
        return job
    def stop_pending(self,job):
        # post_stop is asynchronous. Keep the Python controller and native OCR
        # job alive until their callbacks have finished before unwinding.
        stopping=self.tasker.post_stop() if self.tasker else None
        until=time.monotonic()+5
        while (not job.done or (stopping is not None and not stopping.done)) and time.monotonic()<until:
            time.sleep(.05)
    def check_stop(self):
        if self.stop.is_set():raise UserStopped('用户停止')
    def sleep(self,sec):
        if self.stop.wait(sec):raise UserStopped('用户停止')
    def observe(self, save=None):
        self.check_stop()
        for attempt in range(3):
            if self.wait(self.controller.post_screencap()).succeeded:break
            error=self.controller.last_error or '截图失败'
            # Only retry a read. Inputs are never replayed after a broken pipe,
            # since the device may already have accepted the original click.
            if attempt==2 or not any(part in error.lower() for part in ('error: closed','device offline')):
                raise SafetyStop(error)
            self.log('读取屏幕时连接短暂中断，正在重新读取…');self.sleep(1)
        image=self.controller.cached_image
        if image.shape != (720,1280,3):raise SafetyStop(f'分辨率异常 {image.shape}')
        rebound=getattr(self.controller,'display_reconnected',None)
        if rebound:
            self.log(f'已重新连接超二画面：屏幕 {rebound[0]} → {rebound[1]}')
            self.controller.display_reconnected=None
        result=self.wait(self.tasker.post_recognition('OCR',JOCR(roi=[0,0,1280,720],threshold=.5),image),20).get()
        words=[]
        for node in result.nodes if result else []:
            if node.recognition:
                for r in node.recognition.all_results:
                    if getattr(r,'text','') and r.score>=.5:words.append(Word(r.text,list(r.box),r.score))
        s=Screen(image,words,time.monotonic())
        if save:self.save_screen(s,save)
        return s
    @staticmethod
    def save_screen(s,path):
        Image.fromarray(s.image[:,:,::-1]).save(path)
        Path(path).with_suffix('.json').write_text(json.dumps([vars(w) for w in s.words],ensure_ascii=False,indent=2),encoding='utf-8')
    def guard(self,s):
        self.check_stop()
        if time.monotonic()-s.when>12:raise SafetyStop('画面已过期，请重新观察')
        if s.find('^账号在其他设备登录',(280,170,720,250)) and s.find('^确定$',(450,420,400,150)):
            raise SafetyStop('账号已在其他设备登录，本轮已停止；请恢复本机登录后再开始')
        merchant_pending=getattr(self,'merchant_purchase_pending',None)
        merchant_confirm=False
        if merchant_pending:
            from .merchant import merchant_purchase_confirmation
            merchant_confirm=bool(merchant_purchase_confirmation(s,merchant_pending))
        from .star_shop import star_conversion_confirmation,star_conversion_countdown
        star_pending=getattr(self,'star_conversion_pending',None)
        star_confirm=bool(star_conversion_confirmation(s,star_pending) or
                          star_conversion_countdown(s,star_pending))
        from .piggy_bank import piggy_purchase_confirmation
        piggy_confirm=piggy_purchase_confirmation(s,getattr(self,'piggy_purchase_pending',None))
        if dangerous_dialog(s.text) and not merchant_confirm and not star_confirm and not piggy_confirm and not (getattr(self,'potion_dialog_active',False) and is_stamina_potion_dialog(s)):
            raise SafetyStop('发现补购或资源不足弹窗：已停止，未确认任何消耗')
        if s.find('实名认证|身份证|手机号|验证码|隐私政策|账号密码'):raise SafetyStop('登录或认证界面需要本人处理')
    def match_template(self,s,name,roi,threshold=.88):
        result=self.wait(self.tasker.post_recognition('TemplateMatch',JTemplateMatch(template=[name],roi=roi,threshold=[threshold]),s.image),10).get()
        return bool(result and any(n.recognition and n.recognition.hit for n in result.nodes))
    def read_text_crop(self,s,roi):
        x,y,w,h=roi
        crop=s.image[y:y+h,x:x+w]
        enlarged=np.asarray(Image.fromarray(crop).resize((w*3,h*3))).copy()
        result=self.wait(self.tasker.post_recognition('OCR',JOCR(roi=[0,0,w*3,h*3],only_rec=True,threshold=.8),enlarged),10).get()
        texts=[r.text.strip() for n in result.nodes if n.recognition for r in n.recognition.all_results if hasattr(r,'text') and r.score>=.8] if result else []
        return ''.join(texts)
    def read_number(self,s,roi):
        text=self.read_text_crop(s,roi).replace('O','0').replace('o','0')
        return int(text) if text.isdigit() else None
    def read_text_region(self,s,roi,scale=1,threshold=.65):
        """Detect then recognize a local label; useful for the slanted PvP font."""
        x,y,w,h=roi
        crop=Image.fromarray(s.image[y:y+h,x:x+w]).resize((w*scale,h*scale))
        result=self.wait(self.tasker.post_recognition('OCR',JOCR(roi=[0,0,w*scale,h*scale],threshold=threshold),np.asarray(crop).copy()),10).get()
        texts=[r.text.strip() for n in result.nodes if n.recognition for r in n.recognition.all_results
               if hasattr(r,'text') and r.score>=threshold] if result else []
        return ' '.join(texts)
    def read_resource_ratio(self,s,roi):
        ratio=parse_ratio(s.region_text(roi))
        if ratio is not None:return ratio
        # The narrow slash in the resource font can be read as '[' (7[20).
        # Confirm both numbers independently; never just substitute punctuation.
        word=s.find(r'^\d{1,3}[\[\]]\d{1,3}$',roi)
        if word is None:
            # Full-frame OCR can drop the slash entirely (17/20 -> 1720).
            # Require two local reads to actually see it, agreeing with every
            # digit in the original word. Do not guess a split or a fixed cap.
            word=s.find(r'^\d{2,6}$',roi)
            if word is None or word.score<.8 or self.tasker is None:return None
            x,y,w,h=word.box
            left,top=max(0,x-5),max(0,y-5)
            crop=(left,top,min(s.image.shape[1],x+w+5)-left,min(s.image.shape[0],y+h+5)-top)
            reads=[re.sub(r'\s','',self.read_text_region(s,crop,scale=scale,threshold=.8))
                   for scale in (2,3)]
            if reads[0]!=reads[1] or not re.fullmatch(r'\d{1,3}[/／]\d{1,3}',reads[0]):return None
            if re.sub(r'[/／]','',reads[0])!=word.text:return None
            ratio=parse_ratio(reads[0])
            return ratio if ratio and ratio[1]>0 else None
        left,right=re.fullmatch(r'(\d{1,3})[\[\]](\d{1,3})',word.text).groups();x,y,w,h=word.box
        unit=w/(len(left)+len(right)+1)
        a=self.read_number(s,(x-2,y-2,round(unit*len(left))+3,h+4))
        bx=round(x+unit*(len(left)+1))-2
        b=self.read_number(s,(bx,y-2,x+w-bx+1,h+2))
        return (a,b) if a==int(left) and b==int(right) and b>0 else None
    def confirm_label(self,s,pattern,roi,scale=3,threshold=.5):
        """Full-frame OCR can miss small map labels entirely: the golden
        永生之茧 banner on the world map is undetected on the 1280px frame,
        yet an enlarged crop reads it above .85. Re-read just the region;
        on a hit, append the word so later anchor checks on this screen pass.
        Without a bound tasker (unit tests) this is a no-op."""
        if s.find(pattern,roi) is not None or self.tasker is None:return False
        x,y,w,h=roi
        try:
            crop=Image.fromarray(s.image[y:y+h,x:x+w]).resize((w*scale,h*scale))
            result=self.wait(self.tasker.post_recognition('OCR',JOCR(roi=[0,0,w*scale,h*scale],threshold=threshold),np.asarray(crop).copy()),10).get()
        except UserStopped:raise
        except Exception:return False
        for node in result.nodes if result else []:
            if not node.recognition:continue
            for r in node.recognition.all_results:
                text=getattr(r,'text','')
                if not text or r.score<threshold or not re.search(pattern,text):continue
                bx,by,bw,bh=r.box
                s.words.append(Word(text,[x+bx//scale,y+by//scale,max(1,bw//scale),max(1,bh//scale)],r.score))
                if self.settings.get('trace_inputs'):self.log(f'区域补读确认锚点：{pattern} → {text}')
                return True
        return False
    def click_text(self,s,pattern,roi=None,*,settle_delay=2):
        self.guard(s)
        word=s.find(pattern,roi)
        if not word:raise SafetyStop('未识别按钮：'+pattern)
        # Full-frame OCR preserves character context at the screen edge. Tiny re-OCR
        # crops dropped the first character of task labels on the current client.
        fresh=self.observe();self.guard(fresh)
        x,y=word.center
        again=fresh.find(pattern,(max(0,x-30),max(0,y-30),60,60))
        if not again:raise PageChanged(pattern,fresh)
        if settle_delay==2:self.click_at(fresh,again.center,[pattern],'再次识别后点击文字')
        else:self.click_at(fresh,again.center,[pattern],'再次识别后点击文字',settle_delay=settle_delay)
    def click_at(self,s,point,anchors,reason,*,settle_delay=2):
        self.guard(s)
        if not s.has(*anchors):raise SafetyStop('页面校验不符：'+reason)
        x,y=point
        if not (0<=x<1280 and 0<=y<720):raise SafetyStop('坐标越界')
        if self.settings.get('trace_inputs'):self.log(f'输入：{reason} {x},{y}；锚点：{anchors}')
        self.audit({'action':'click','reason':reason,'point':[x,y],'anchors':anchors,'status':'requested'})
        if not self.wait(self.controller.post_click(x,y)).succeeded:raise SafetyStop(self.controller.last_error or '点击失败')
        self.audit({'action':'click','reason':reason,'point':[x,y],'status':'sent'})
        self.sleep(settle_delay)
    def launch_game(self):
        # Only called by the explicit launch button, never during a task retry.
        adb=Path(self.settings.get('adb',DEFAULT_ADB));manager=adb.with_name('MuMuManager.exe')
        index=str(self.settings.get('mumu_index',0))
        def manager_cmd(*args):
            return subprocess.run([str(manager),*args],capture_output=True,check=True,timeout=15,creationflags=NO_WINDOW).stdout.decode('utf-8','replace')
        if manager.exists():
            info=json.loads(manager_cmd('info','-v',index))
            if not info.get('is_android_started'):
                self.log('正在启动 MuMu，请稍候…');manager_cmd('control','-v',index,'launch')
                for attempt in range(45):
                    self.sleep(2);info=json.loads(manager_cmd('info','-v',index))
                    if info.get('is_android_started'):break
                    if attempt%5==4:self.log(f'等待 MuMu 启动，已等待{(attempt+1)*2}秒…')
                else:raise SafetyStop('MuMu 启动超时，请手动打开模拟器')
            manager_cmd('control','-v',index,'app','launch','-pkg',PACKAGE)
        else:
            subprocess.run([str(adb),'connect',self.settings.get('address','127.0.0.1:16384')],capture_output=True,timeout=8,creationflags=NO_WINDOW)
            subprocess.run([str(adb),'-s',self.settings.get('address','127.0.0.1:16384'),'shell','am','start','-n',ACTIVITY],capture_output=True,check=True,timeout=12,creationflags=NO_WINDOW)
