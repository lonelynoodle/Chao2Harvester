"""Dismiss incidental lore without navigating away or replaying the task."""
import re

from .policy import TaskBlocked


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
    note('检测到故事卡“'+title+'”，关闭后继续当前任务')
    checkpoint()

    def closed(after):
        row['status']='closed'
        report.setdefault('map_stories',[]).append(title)
        note('已关闭故事卡“'+title+'”，继续原任务')
        checkpoint()
        return after

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
