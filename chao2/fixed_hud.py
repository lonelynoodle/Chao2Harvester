"""Fixed HUD crops ending exactly at the black number panel's right edge."""
import re

FOREST_POINTS_ROI=(1110,10,70,32)  # Right edge x=1180; exclude the bright map art.
TOWER_MAP_ROI=(1110,10,70,32)     # The map/secret-list HUD uses the same panel.
TOWER_DETAIL_ROI=(1183,10,80,32)  # Detail/result panel ends at x=1263.
HUD_SCALES=(3,4,2)


def fixed_hud_ratio(b,s,roi):
    """Require agreeing complete local reads; never split digits or reuse OCR boxes."""
    reads=[];confirmed=None
    def parse(raw):
        text=re.sub(r'\s+','',raw).replace('／','/')
        match=re.fullmatch(r'(\d{1,3})/(\d{1,3})',text)
        if not match:return None
        pair=tuple(map(int,match.groups()))
        return pair if pair[1]>0 else None
    for scale in HUD_SCALES:
        raw=b.read_text_region(s,roi,scale=scale,threshold=.8)
        reads.append(f'{scale}倍={raw!r}')
        pair=parse(raw)
        if pair is None:continue
        if confirmed is not None:return (pair if pair==confirmed else None),reads
        confirmed=pair
    if confirmed is not None and b.tasker is not None:
        # Independent recognition uses the SAME fixed boundary, including
        # when the text detector omitted the number at the other scales.
        raw=b.read_text_crop(s,roi);reads.append(f'独立识别={raw!r}')
        if parse(raw)==confirmed:return confirmed,reads
    return None,reads


def tower_feathers(b,s,*,map_view=False):
    if b.tasker is None:return None
    roi=TOWER_MAP_ROI if map_view else TOWER_DETAIL_ROI
    pair,reads=fixed_hud_ratio(b,s,roi)
    if pair is None:b.log('浮空羽毛固定区域未确认：'+'；'.join(reads))
    return pair
