"""Image registration only. No Windows input, game process or network access."""
from security import ValidationError
from dataclasses import dataclass
from pathlib import Path
import math
import time
import cv2
import numpy as np

@dataclass
class Registration:
    matrix: np.ndarray | None
    status: str
    inliers: int = 0
    error: float = 0.0
    header_score: float = 0.0
    milliseconds: float = 0.0
    bounds: tuple | None = None
    shape: str = "rectangle"

class TerrainTracker:
    def __init__(self, assets, max_width=1280, reference_path=None, use_header=True):
        self.assets = Path(assets)
        self.reference = cv2.imread(str(reference_path or self.assets / 'reference.png'), cv2.IMREAD_GRAYSCALE)
        self.header = cv2.imread(str(self.assets / 'map-header.png'), cv2.IMREAD_GRAYSCALE) if use_header else None
        if self.reference is None or (use_header and self.header is None):
            raise ValidationError('Reference assets are missing or unreadable.')
        self.max_width = max_width
        cv2.setNumThreads(2)
        self.sift = cv2.SIFT_create(nfeatures=2600, contrastThreshold=.018, edgeThreshold=14)
        self.keypoints, self.descriptors = self.sift.detectAndCompute(self.reference, None)
        if self.descriptors is None or len(self.keypoints)<8:raise ValidationError('This picture has too little terrain detail for alignment. Import a clearer map crop.')
        self.matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=4), dict(checks=64))
        self._header_templates = {}
        self.previous_gray = None
        self.flow_world = None
        self.flow_screen = None
        self.last_absolute = -100.0
        self.previous_timestamp = None

    @staticmethod
    def viewport(width, height):
        # The supplied full-screen map has a fixed sidebar, top tabs and right controls.
        return (round(.18 * width), round(.10 * height), round(.945 * width), round(.965 * height))

    def feature_mask(self,width,height,factor,small):
        mask=np.zeros(small.shape,np.uint8)
        left,top,right,bottom=self.viewport(width,height)
        mask[round(top*factor):round(bottom*factor),round(left*factor):round(right*factor)]=255
        return mask

    def terrain_contains(self,points,width,height):
        l,t,r,b=self.viewport(width,height)
        return (points[:,0]>l)&(points[:,0]<r)&(points[:,1]>t)&(points[:,1]<b)

    def map_visible(self, gray):
        if self.header is None:return True,1.0
        h, w = gray.shape
        # Accommodate fixed UI sizing and common resolution/UI-scale changes.
        region = gray[:max(90, round(.115*h)), :max(390, round(.23*w))]
        size = (w, h)
        if size not in self._header_templates:
            factors = sorted(set(round(s, 2) for s in (1.0, w/1920, .75, 1.25, 1.5)))
            templates = []
            for factor in factors:
                template = cv2.resize(self.header, None, fx=factor, fy=factor)
                if template.shape[0] <= region.shape[0] and template.shape[1] <= region.shape[1]:
                    templates.append(template)
            self._header_templates[size] = templates
        score = 0.0
        for template in self._header_templates[size]:
            score = max(score, float(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED).max()))
        return score >= .78, score

    def register(self, image, timestamp=None):
        started = time.perf_counter()
        timestamp = started if timestamp is None else timestamp
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        visible, header_score = self.map_visible(gray)
        def result(matrix, status, inliers=0, error=0.0):
            return Registration(matrix, status, inliers, error, header_score, (time.perf_counter()-started)*1000)
        if not visible:
            self.previous_gray = None
            self.flow_world = None
            return result(None, 'Map closed / different region')
        h, w = gray.shape
        factor = min(1.0, self.max_width/w)
        small = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        # Optical flow follows terrain between absolute re-locks. It never
        # estimates map movement from mouse input. Forward/backward checks,
        # patch error and the same geometric tests reject unreliable motion.
        if (self.previous_gray is not None and self.previous_gray.shape == small.shape
            and self.flow_world is not None and len(self.flow_world) >= 8
            and self.previous_timestamp is not None
            and 0 < timestamp-self.previous_timestamp < .30
            and timestamp-self.last_absolute < .65):
            old = self.flow_screen.reshape(-1,1,2).astype(np.float32)
            new, ok, err = cv2.calcOpticalFlowPyrLK(self.previous_gray, small, old, None,
                    winSize=(31,31), maxLevel=4,
                    criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.01))
            if new is not None:
                back, reverse_ok, reverse_err = cv2.calcOpticalFlowPyrLK(small, self.previous_gray, new, None,
                        winSize=(31,31), maxLevel=4,
                        criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.01))
                if back is not None:
                    forward_back = np.linalg.norm(back.reshape(-1,2)-old.reshape(-1,2),axis=1)
                    live = new.reshape(-1,2)
                    l,t,r,b = self.viewport(w,h)
                    keep = ((ok.ravel()>0)&(reverse_ok.ravel()>0)&(forward_back<.9)&(err.ravel()<18)
                        &self.terrain_contains(live/factor,w,h))
                    if keep.sum() >= 8:
                        tracked = self._fit(self.flow_world[keep], live[keep]/factor, w)
                        if tracked is not None:
                            affine, count, error, inside = tracked
                            self.flow_world = self.flow_world[keep][inside]
                            self.flow_screen = live[keep][inside]
                            self.previous_gray = small
                            self.previous_timestamp = timestamp
                            return result(affine, 'Tracking terrain (flow)', count, error)
        self.previous_gray = None
        mask=self.feature_mask(w,h,factor,small)
        keypoints, descriptors = self.sift.detectAndCompute(small, mask)
        if descriptors is None or len(keypoints) < 8:
            return result(None, 'Not enough visible terrain')
        pairs = self.matcher.knnMatch(self.descriptors, descriptors, k=2)
        # A train point may be the best match of many repeated resource icons.
        # Keep unique train IDs AND unique source/target positions before fitting.
        candidates = sorted((pair[0] for pair in pairs if len(pair)==2 and pair[0].distance < .72*pair[1].distance), key=lambda match: match.distance)
        source_cells, target_cells, selected = set(), set(), []
        for match in candidates:
            a = self.keypoints[match.queryIdx].pt
            b = keypoints[match.trainIdx].pt
            ca, cb = (round(a[0]/3), round(a[1]/3)), (round(b[0]/3), round(b[1]/3))
            if ca in source_cells or cb in target_cells:
                continue
            source_cells.add(ca); target_cells.add(cb); selected.append(match)
        if len(selected) < 8:
            return result(None, 'Route area off-screen / reacquiring')
        src = np.float32([self.keypoints[m.queryIdx].pt for m in selected])
        dst = np.float32([keypoints[m.trainIdx].pt for m in selected]) / factor
        fitted = self._fit(src, dst, w)
        if fitted is None:
            return result(None, 'Uncertain alignment / route area off-screen')
        affine, count, error, inside = fitted
        self.flow_world = src[inside]
        self.flow_screen = dst[inside]*factor
        self.previous_gray = small
        self.previous_timestamp = timestamp
        self.last_absolute = timestamp
        return result(affine, 'Tracking terrain', count, error)

    def _fit(self, src, dst, width):
        cv2.setRNGSeed(2731)
        matrix, inside = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                ransacReprojThreshold=3.5, maxIters=3000, confidence=.999)
        if matrix is None or inside is None:
            return None
        keep = inside.ravel().astype(bool)
        count = int(keep.sum())
        scale = math.hypot(matrix[0,0], matrix[1,0])
        rotation = abs(math.degrees(math.atan2(matrix[1,0], matrix[0,0])))
        spread_src = np.ptp(src[keep], axis=0) if count else np.zeros(2)
        spread_dst = np.ptp(dst[keep], axis=0) if count else np.zeros(2)
        if count < 7 or count/len(src) < .42 or not .20 <= scale/(width/1920) <= 8 or rotation > 1.5 or min(spread_src) < 30 or min(spread_dst) < 32:
            return None
        a, b = src[keep].astype(float), dst[keep].astype(float)
        ac, bc = a-a.mean(axis=0), b-b.mean(axis=0)
        slope = float((ac*bc).sum()/(ac*ac).sum())
        offset = b.mean(axis=0)-slope*a.mean(axis=0)
        affine = np.array([[slope, 0, offset[0]], [0, slope, offset[1]]], dtype=float)
        errors = np.linalg.norm(a*slope+offset-b, axis=1)
        error = float(np.median(errors))
        if error > 2.5 or np.percentile(errors,90) > 4.5:
            return None
        return affine, count, error, keep



def project(matrix, points):
    points = np.asarray(points, dtype=float)
    if len(points) == 0:
        return np.empty((0,2))
    return points @ matrix[:,:2].T + matrix[:,2]


def clip_segment(a, b, bounds):
    """Liang-Barsky clip in screen coordinates; no line drawn over sidebar."""
    left, top, right, bottom = bounds
    dx, dy = b[0]-a[0], b[1]-a[1]
    start, end = 0.0, 1.0
    for p,q in ((-dx,a[0]-left),(dx,right-a[0]),(-dy,a[1]-top),(dy,bottom-a[1])):
        if abs(p)<1e-12:
            if q<0: return None
            continue
        t=q/p
        if p<0:
            if t>end:return None
            start=max(start,t)
        else:
            if t<start:return None
            end=min(end,t)
    return (a[0]+start*dx,a[1]+start*dy,a[0]+end*dx,a[1]+end*dy)


def inside_map(x,y,bounds,shape='rectangle',margin=0):
    left,top,right,bottom=bounds
    left+=margin;top+=margin;right-=margin;bottom-=margin
    if left>=right or top>=bottom or not left<=x<=right or not top<=y<=bottom:return False
    if shape!='ellipse':return True
    return ((x-(left+right)/2)/((right-left)/2))**2+((y-(top+bottom)/2)/((bottom-top)/2))**2<=1+1e-10


def clip_map_segment(a,b,bounds,shape='rectangle'):
    if shape!='ellipse':return clip_segment(a,b,bounds)
    l,t,r,bottom=bounds;rx,ry=(r-l)/2,(bottom-t)/2
    if rx<=0 or ry<=0:return None
    origin=(np.asarray(a,dtype=float)-((l+r)/2,(t+bottom)/2))/(rx,ry)
    delta=(np.asarray(b,dtype=float)-a)/(rx,ry)
    aa=float(delta@delta);bb=2*float(origin@delta);cc=float(origin@origin)-1
    if aa<1e-20:return (tuple(a),tuple(b)) if cc<=0 else None
    disc=bb*bb-4*aa*cc
    if disc<0:return None
    root=math.sqrt(disc);start=max(0,(-bb-root)/(2*aa));end=min(1,(-bb+root)/(2*aa))
    if start>end:return None
    direction=np.asarray(b,dtype=float)-a
    return tuple(np.asarray(a)+start*direction),tuple(np.asarray(a)+end*direction)
