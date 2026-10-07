"""Recognize a resource sprite only around a click on the saved reference image.

This never scans a game capture or generates a resource database. Matches are
image estimates; catalog entries remain the source of exact item names.
"""
from pathlib import Path
import math
import cv2
import numpy as np
from PIL import Image
from routes import KINDS
from security import ValidationError
import uuid

def import_samples(source,destination):
    source=Path(source);destination=Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    available=100-len(list(destination.glob('*.png')));count=0
    if available<=0:raise ValidationError('Maximum 100 learned icons. Remove unused samples before importing more.')
    for path in sorted(source.glob('*.png'))[:100]:
        kind=path.stem.split('-')[0]
        if kind not in KINDS or kind in ('Custom','Waypoint'):continue
        try:
            if path.stat().st_size>100_000:continue
            with Image.open(path) as im:
                if min(im.size)<6 or max(im.size)>96:continue
                rgba=np.array(im.convert('RGBA'))
            clean=Image.fromarray(rgba)
            suffix='-legend' if 'legend' in path.stem else ''
            clean.save(destination/(kind+'-'+uuid.uuid4().hex+suffix+'.png'),format='PNG')
            count+=1
            if count>=available:break
        except (OSError,ValueError):continue
    if not count:raise ValidationError('No valid icon samples found. Choose a folder of resource-type PNG samples.')
    return count

def save_sample(image,kind,folder):
    """Save a user-selected icon crop locally without image metadata."""
    if kind not in KINDS or kind in ('Custom','Waypoint'):raise ValidationError('Choose a resource Type before teaching its icon.')
    if min(image.size)<6 or max(image.size)>64:raise ValidationError('Select a tight icon crop between 6 and 64 pixels across.')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    if len(list(folder.glob('*.png')))>=100:raise ValidationError('Maximum 100 learned icons. Remove unused local icon samples before adding more.')
    rgb=np.asarray(image.convert('RGB'))
    edges=np.concatenate([rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]])
    background=np.median(edges,axis=0)
    mask=(np.max(np.abs(rgb.astype(float)-background),axis=2)>25).astype(np.uint8)*255
    if np.count_nonzero(mask)<20:raise ValidationError('This crop has too little icon detail. Select the resource symbol closely.')
    clean=Image.fromarray(np.dstack([rgb,mask]))
    path=folder/(kind+'-'+uuid.uuid4().hex+'.png');clean.save(path,format='PNG');return path


class IconTypes:
    def __init__(self, image, templates=None, user_templates=None):
        self.image=np.asarray(image.convert('RGB'),dtype=np.float32)
        self.templates=[]
        folder=templates or Path(__file__).resolve().parent/'assets'/'icon-types'
        paths=sorted(Path(folder).glob('*.png'))[:100]
        if user_templates:paths+=sorted(Path(user_templates).glob('*.png'))[:100]
        for path in paths:
            kind=path.stem.split('-')[0]
            if kind not in KINDS or kind in ('Custom','Waypoint'):continue
            try:
                if path.stat().st_size>100_000:continue
                with Image.open(path) as sprite:
                    if min(sprite.size)<6 or max(sprite.size)>96:continue
                    rgba=np.array(sprite.convert('RGBA'))
            except (OSError,ValueError):continue
            for scale in (.7,.85,1,1.15,1.3,1.5,1.75,2,2.5,3):
                w,h=round(rgba.shape[1]*scale),round(rgba.shape[0]*scale)
                if min(w,h)<7 or max(w,h)>80:continue
                rgb=cv2.resize(rgba[:,:,:3],(w,h)).astype(np.float32)
                mask=cv2.resize(rgba[:,:,3],(w,h),interpolation=cv2.INTER_NEAREST)
                if np.count_nonzero(mask)<20:continue
                # Legend icons are dimmer and less detailed than map sprites.
                self.templates.append((kind,rgb,mask,'legend' in path.stem))

    def candidates(self, x, y):
        """Return per-category scores, for diagnostics as well as recognition."""
        best={}
        height,width=self.image.shape[:2]
        for kind,sprite,mask,legend in self.templates:
            h,w=sprite.shape[:2]
            # A small tolerance lets a click on the icon's edge find its center.
            radius=min(9,max(4,round(max(w,h)*.35)))
            left=max(0,int(x-(w-1)/2-radius));top=max(0,int(y-(h-1)/2-radius))
            right=min(width,int(x+(w-1)/2+radius+2));bottom=min(height,int(y+(h-1)/2+radius+2))
            patch=self.image[top:bottom,left:right]
            if patch.shape[0]<h or patch.shape[1]<w:continue
            distance=cv2.matchTemplate(patch,sprite,cv2.TM_SQDIFF_NORMED,mask=mask)
            correlation=cv2.matchTemplate(patch,sprite,cv2.TM_CCOEFF_NORMED,mask=mask)
            yy,xx=np.indices(distance.shape)
            dx=left+xx+(w-1)/2-x;dy=top+yy+(h-1)/2-y
            score=distance+.45*(1-correlation)+.002*(dx*dx+dy*dy)
            score[~np.isfinite(score)]=10
            at=np.unravel_index(np.argmin(score),score.shape)
            candidate=dict(Kind=kind,Score=float(score[at]),Correlation=float(correlation[at]),Distance=float(distance[at]),X=float(left+at[1]+(w-1)/2),Y=float(top+at[0]+(h-1)/2),Legend=legend)
            if kind not in best or candidate['Score']<best[kind]['Score']:best[kind]=candidate
        return sorted(best.values(),key=lambda item:item['Score'])

    def identify(self, x, y):
        """Return a typed estimated point, or None when the image is ambiguous."""
        if not math.isfinite(x) or not math.isfinite(y):return None
        height,width=self.image.shape[:2]
        if not 0<=x<width or not 0<=y<height:return None
        matches=self.candidates(x,y)
        if not matches:return None
        first=matches[0]
        limit=(.16 if first['Kind'] in ('Trees','Ore','Shellfish') else .21) if first['Legend'] else .24
        if first['Score']>limit or first['Correlation']<.72 or first['Distance']>.16:return None
        if len(matches)>1 and matches[1]['Score']-first['Score']<.055:return None
        return dict(X=first['X'],Y=first['Y'],Kind=first['Kind'],Source='Reference icon match (estimate)')
