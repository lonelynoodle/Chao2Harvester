"""Claim incidental lore rewards and resume without replaying the task."""
import re

from .policy import TaskBlocked

STORY_CHEST_ROI=(175,530,125,115)
ECHO_UPGRADE_EFFECT=r'^(?:移动力上限|黑暗森林探索点上限)$'
ECHO_UPGRADE_DISMISS=r'^点击空白位置关闭$'


def map_story_chest_state(s):
    if story_identity(s) is None:return None
    if s.find('^已领[取奖]$',STORY_CHEST_ROI):return 'claimed'
    if s.find('^可领取$',STORY_CHEST_ROI):return 'ready'
    from .other_tasks import notification_badges
    return 'ready' if notification_badges(s,STORY_CHEST_ROI) else None


def story_echo_upgrade(s):
    return bool(s.find('^回响等级$',(650,180,400,95)) and
                s.find(ECHO_UPGRADE_EFFECT,(650,270,400,95)) and
                s.find(ECHO_UPGRADE_DISMISS,(490,570,500,95)))


def close_story_echo_upgrade(b,s):
    anchors=['^回响等级$',ECHO_UPGRADE_EFFECT,ECHO_UPGRADE_DISMISS]
    for attempt in range(4):
        b.guard(s)
        if story_echo_upgrade(s):
            b.click_at(s,(640+4*attempt,620),anchors,'关闭回响等级提升提示')
        for _ in range(5):
            s=b.observe();b.guard(s)
            if s.words and not s.find('^回响等级$',(650,180,400,95)):return s
            b.sleep(.5)
    raise TaskBlocked('回响等级提升提示关闭后仍未确认下一页面')


def complete_story_card_reward(b,report,row,*,checkpoint=lambda:None):
    """Only finish an already submitted free claim, including its level-up."""
    from .reward_collection import reward_overlay
    identity=(row['number'],row['title']);received=bool(row.get('reward_text'))
    for _ in range(16):
        after=b.observe();b.guard(after)
        if story_echo_upgrade(after):
            row.setdefault('level_ups',[]).append(after.text)
            if report.get('folder'):b.save_screen(after,report['folder']/f'story-reward-{len(report["story_rewards"])}-level-up.png')
            checkpoint()
            after=close_story_echo_upgrade(b,after)
        if reward_overlay(after):
            row.update(status='received',reward_text=after.text);received=True
            if report.get('folder'):b.save_screen(after,report['folder']/f'story-reward-{len(report["story_rewards"])}.png')
            checkpoint()
            b.click_at(after,(640,660),['^获得奖励$'],'关闭故事宝箱奖励')
            continue
        if story_identity(after)==identity:
            state=map_story_chest_state(after)
            if state=='claimed' or (received and state!='ready'):
                row.update(status='claimed',confirmation='claimed_label' if state=='claimed' else 'receipt')
                checkpoint();return after
        elif received and after.words:
            # Some cards disappear with the reward. Return the new page
            # without clicking the preceding card's close coordinates.
            row.update(status='claimed',confirmation='receipt');checkpoint();return after
        b.sleep(.5)
    row['status']='unconfirmed';checkpoint()
    raise TaskBlocked('故事宝箱领取结果未确认，未重复领取或重做原任务')


def claim_story_card_reward(b,s,report,note,*,source_task=None,source_id=None,checkpoint=lambda:None):
    """One free claim, then confirm receipt before closing the lore card."""
    from .reward_collection import COMMENT
    identity=story_identity(s)
    if identity is None or map_story_chest_state(s)!='ready':return s
    fresh=b.observe();b.guard(fresh)
    if story_identity(fresh)!=identity or map_story_chest_state(fresh)!='ready':return fresh
    rows=report.setdefault('story_rewards',[])
    if any((r.get('number'),r.get('title'))==identity and r.get('status') in ('opening','unconfirmed') for r in rows):
        raise TaskBlocked('故事宝箱上次领取结果未确认，未重复领取')
    number,title=identity
    row={'number':number,'title':title,'source_task':source_task,'instance_id':source_id,'status':'opening'}
    rows.append(row);checkpoint()
    note('领取故事“'+title+'”的免费宝箱')
    b.click_at(fresh,(235,588),[COMMENT,'^'+re.escape(number)+'$','^'+re.escape(title)+'$'],
               '领取事件故事卡免费宝箱')
    return complete_story_card_reward(b,report,row,checkpoint=checkpoint)


def story_identity(s):
    from .reward_collection import is_map_story
    if not is_map_story(s):return None
    number=s.find(r'^\d{3,4}$',(365,165,100,55))
    title=s.find(r'^.{2,16}$',(370,210,550,70))
    return number.text,title.text


def close_story_card(b,s,report,note,*,source_task=None,source_id=None,checkpoint=lambda:None):
    """Only retry the free close while the same numbered card is still visible.

    Read raw frames here: calling Daily.observe would recursively dismiss the
    same card. Return the actual underlying page to the caller's current step.
    """
    from .reward_collection import COMMENT
    identity=story_identity(s)
    if identity is None:raise TaskBlocked('事件故事卡未确认')
    b.guard(s)
    number,title=identity
    rows=report.setdefault('story_interruptions',[])
    row={'number':number,'title':title,'source_task':source_task,
         'instance_id':source_id,'status':'observed','close_attempts':0}
    rows.append(row)
    if report.get('folder'):
        path=report['folder']/f'story-interruption-{len(rows)}.png'
        b.save_screen(s,path);row['screenshot']=str(path)
    note('检测到故事卡“'+title+'”，检查免费宝箱后继续当前任务')
    checkpoint()

    def closed(after):
        row['status']='closed'
        report.setdefault('map_stories',[]).append(title)
        note('已关闭故事卡“'+title+'”，继续原任务')
        checkpoint()
        return after

    s=claim_story_card_reward(b,s,report,note,source_task=source_task,source_id=source_id,checkpoint=checkpoint)
    for attempt in range(4):
        b.guard(s)
        if story_identity(s)!=identity:
            # A different card or page must be handled from its own fresh
            # observation, never with the preceding card's close coordinates.
            if s.words:return closed(s)
            row['status']='unconfirmed';checkpoint()
            raise TaskBlocked('故事卡关闭后页面尚未稳定，未追加输入')
        if attempt:note(f'故事卡“{title}”仍在，重试关闭 {attempt}/3')
        b.click_at(s,(1210,650),[COMMENT,r'^'+re.escape(number)+'$',
                               '^'+re.escape(title)+'$'],
                   '关闭事件故事卡，继续原任务')
        row['close_attempts']+=1
        for _ in range(6):
            s=b.observe();b.guard(s)
            if s.words and story_identity(s)!=identity:return closed(s)
            b.sleep(.5)
    row['status']='blocked';checkpoint()
    raise TaskBlocked('事件故事卡关闭后仍在，已重试3次；保留现场，未重复执行原任务')
