"""Verify a copied lineup from the five selected portrait cards and the god.

Power is an OCR hint only. Portrait matching uses the current source row and
fresh destination pixels, so an old full lineup cannot pass just by counting
five cards. Card order may differ in the inventory strip.
"""
import cv2
import numpy as np
import re


def saved_team_rows(screen):
    """Pair fixed-column team names with their own copy buttons.

    Server announcements can completely cover the modal title. The repeated
    row structure remains visible and is more specific than that title alone.
    """
    rows=[]
    for word in screen.words:
        if word.score<.8 or not re.fullmatch(r'队伍[1-9]',word.text):continue
        x,y=word.center
        if not (285<=x<485 and 80<=y<670):continue
        button=screen.find('^复制此配置$',(745,y-27,200,54))
        if button is not None and button.score>=.8:rows.append((word,button))
    return sorted(rows,key=lambda row:row[0].center[1])


def is_saved_team_list(screen):
    rows=saved_team_rows(screen)
    if not rows:return False
    if screen.find('^配置$',(450,0,380,90)):return True
    # Two distinct, separated rows prevent a stray team label/copy button in
    # another panel from authorizing modal navigation.
    return any(a[0].text!=b[0].text and abs(a[0].center[1]-b[0].center[1])>=100
               for a in rows for b in rows)


def saved_team_anchors(screen):
    if not is_saved_team_list(screen):return []
    rows=saved_team_rows(screen)
    return ['^复制此配置$']+['^'+re.escape(row[0].text)+'$' for row in rows[:2]]


def saved_team_copy_target(b,screen,team):
    """Pair the requested preset with its own button on this same fresh frame."""
    if not is_saved_team_list(screen):return None
    rows=[w for w in screen.words if w.text=='队伍'+str(team) and w.score>=.8 and
          285<=w.center[0]<485 and 80<=w.center[1]<=530]
    if len(rows)!=1:return None
    row=rows[0];roi=(745,row.center[1]-27,200,54)
    button=screen.find('^复制此配置$',roi)
    if button is None:
        # The neighboring rows remain readable when full-frame OCR drops just
        # this button. Recover actual text locally, never use a fixed-row click.
        b.confirm_label(screen,'^复制此配置$',roi,scale=3,threshold=.8)
        button=screen.find('^复制此配置$',roi)
    return (row,button) if button and button.score>=.8 else None


def source_lineup(image,row_y):
    y=int(row_y)
    if y+110>image.shape[0]:return None
    portraits=[image[y+54:y+89,402+i*80:462+i*80].copy() for i in range(5)]
    god=image[y+39:y+110,795:963].copy()
    if any(p.size==0 or p.std()<8 for p in [*portraits,god]):return None
    return {'portraits':portraits,'god':god}


def copied_lineup(source,image):
    if source is None:return {'verified':False,'reason':'源配置头像未读清'}
    region=cv2.cvtColor(image[612:680,110:1280],cv2.COLOR_BGR2GRAY)
    hits=[];scores=[]
    for portrait in source['portraits']:
        gray=cv2.cvtColor(portrait,cv2.COLOR_BGR2GRAY);best=(0,None)
        for scale in np.arange(1.4,1.91,.025):
            patch=cv2.resize(gray,None,fx=scale,fy=scale)
            _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(region,patch,cv2.TM_CCOEFF_NORMED))
            if score>best[0]:best=(score,point)
        score,point=best;scores.append(round(float(score),3))
        if score<.84 or point is None:continue
        x=point[0]+110
        # Selected cards have a green check in their upper-left corner. The
        # same portrait in the unselected inventory is insufficient evidence.
        tick=image[590:625,max(0,x-18):x+12].astype('int16')
        b,g,r=(tick[:,:,i] for i in range(3))
        if ((g>115)&(g>r*1.15)&(g>b*1.15)).mean()<.025:continue
        if all(abs(x-old)>65 for old in hits):hits.append(x)
    god_verified=False
    if len(hits)==5:
        sift=cv2.SIFT_create(contrastThreshold=.015)
        god=cv2.cvtColor(source['god'],cv2.COLOR_BGR2GRAY)
        scene=cv2.cvtColor(image[70:300,230:510],cv2.COLOR_BGR2GRAY)
        a,da=sift.detectAndCompute(god,None);b,db=sift.detectAndCompute(scene,None)
        if da is not None and db is not None and len(db)>=2:
            pairs=cv2.BFMatcher().knnMatch(da,db,k=2)
            good=[m for pair in pairs if len(pair)==2 for m,n in [pair]
                  if m.distance<.7*n.distance and a[m.queryIdx].pt[0]>60]
            if len(good)>=4:
                start=np.float32([a[m.queryIdx].pt for m in good])
                end=np.float32([b[m.trainIdx].pt for m in good])
                matrix,inliers=cv2.estimateAffinePartial2D(start,end,method=cv2.RANSAC,ransacReprojThreshold=5)
                if matrix is not None:
                    scale=float(np.hypot(matrix[0,0],matrix[0,1]))
                    god_verified=bool(inliers.sum()>=4 and .65<scale<4 and abs(matrix[0,1])<scale*.3)
    return {'verified':len(hits)==5 and god_verified,'matched_monsters':len(hits),
            'god_verified':god_verified,'portrait_scores':scores}
