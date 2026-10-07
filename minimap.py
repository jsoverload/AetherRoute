"""Bounded map-panel registration, including rotation. No game state access."""
from security import ValidationError
import math
import cv2
import numpy as np
from tracking import TerrainTracker, inside_map


def settings(value):
    """Validate the optional client-relative screen area before use or import."""
    if value is None:return None
    if not isinstance(value,dict):raise ValidationError('Invalid minimap settings.')
    bounds=value.get('bounds');shape=value.get('shape','rectangle')
    if not isinstance(bounds,(list,tuple)) or len(bounds)!=4 or shape not in ('rectangle','ellipse'):raise ValidationError('Invalid minimap area or shape.')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds):raise ValidationError('Invalid minimap coordinates.')
    l,t,r,b=map(float,bounds)
    if not 0<=l<r<=1 or not 0<=t<b<=1 or r-l<.025 or b-t<.025:raise ValidationError('Minimap area must be inside the game window.')
    return dict(bounds=[l,t,r,b],shape=shape)


def pixel_bounds(config,width,height):
    config=settings(config)
    if config is None:return None
    l,t,r,b=config['bounds'];box=(round(l*width),round(t*height),round(r*width),round(b*height))
    if box[2]-box[0]<64 or box[3]-box[1]<64:return None
    return box


class PanelTerrain(TerrainTracker):
    def __init__(self,assets,reference_path,shape):
        self.shape=shape
        super().__init__(assets,max_width=1000,reference_path=reference_path,use_header=False)

    @staticmethod
    def viewport(width,height):return (3,3,width-3,height-3)

    def feature_mask(self,width,height,factor,small):
        mask=np.zeros(small.shape,np.uint8)
        l,t,r,b=self.viewport(width,height)
        if self.shape=='ellipse':cv2.ellipse(mask,(round((l+r)*factor/2),round((t+b)*factor/2)),(round((r-l)*factor/2),round((b-t)*factor/2)),0,0,360,255,-1)
        else:mask[round(t*factor):round(b*factor),round(l*factor):round(r*factor)]=255
        return mask

    def terrain_contains(self,points,width,height):
        return np.array([inside_map(x,y,self.viewport(width,height),self.shape) for x,y in points])

    def _fit(self,src,dst,width):
        cv2.setRNGSeed(2731)
        matrix,inside=cv2.estimateAffinePartial2D(src,dst,method=cv2.RANSAC,ransacReprojThreshold=2.5,maxIters=4000,confidence=.999)
        if matrix is None or inside is None:return None
        keep=inside.ravel().astype(bool);count=int(keep.sum())
        scale=math.hypot(matrix[0,0],matrix[1,0])
        if count<10 or count/len(src)<.45 or not .12<=scale<=12:return None
        a,b=src[keep].astype(float),dst[keep].astype(float)
        if min(np.ptp(a,axis=0))<20 or min(np.ptp(b,axis=0))<18:return None
        # A line/repeated icon cluster is not enough to anchor a whole panel.
        if cv2.contourArea(cv2.convexHull(b.astype(np.float32)))<max(220,width*width*.008):return None
        errors=np.linalg.norm(a@matrix[:,:2].T+matrix[:,2]-b,axis=1)
        error=float(np.median(errors))
        if error>1.8 or np.percentile(errors,90)>3.5:return None
        return matrix,count,error,keep


class MinimapTracker:
    def __init__(self,assets,reference_path,config):
        self.config=settings(config);self.panel=None;self.last_bounds=None
        if self.config:self.panel=PanelTerrain(assets,reference_path,self.config['shape'])

    def register(self,image,timestamp=None):
        from tracking import Registration
        h,w=image.shape[:2];bounds=pixel_bounds(self.config,w,h)
        if bounds is None:return Registration(None,'Set the minimap area in the Overlay tab')
        if bounds!=self.last_bounds:
            self.panel.previous_gray=None;self.panel.flow_world=None;self.last_bounds=bounds
        l,t,r,b=bounds
        result=self.panel.register(image[t:b,l:r],timestamp)
        result.bounds=bounds;result.shape=self.config['shape']
        if result.matrix is not None:
            result.matrix=result.matrix.copy();result.matrix[:,2]+=(l,t)
            result.status='Minimap aligned'+(' (flow)' if 'flow' in result.status else '')
        else:result.status='Minimap hidden / terrain uncertain'
        return result
