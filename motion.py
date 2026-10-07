"""Cheap visual movement gate, independent of terrain registration."""
import cv2
import numpy as np

class MotionGate:
    def __init__(self,settle=.30):
        self.settle=settle;self.previous=None;self.previous_time=None;self.changed_at=None;self.ready=False
    def reset(self):
        self.previous=None;self.previous_time=None;self.changed_at=None;self.ready=False
    def hold(self,now):
        self.changed_at=now;self.ready=False
    def update(self,image,now,held=False):
        h,w=image.shape[:2]
        crop=image[round(.14*h):round(.94*h),round(.23*w):round(.91*w)]
        gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY) if crop.ndim==3 else crop
        small=cv2.resize(gray,(360,220),interpolation=cv2.INTER_AREA)
        small=cv2.GaussianBlur(small,(5,5),0)
        discontinuity=self.previous_time is None or now-self.previous_time>.35
        moving=self.previous is None or self.previous.shape!=small.shape or discontinuity
        if not moving:
            diff=cv2.absdiff(small,self.previous)
            # Ignore a cursor/individual icon; broad terrain motion affects many pixels.
            moving=float(np.mean(diff>8))>.055 or float(np.mean(diff))>4.0
        if moving or held:self.hold(now)
        self.previous=small;self.previous_time=now
        self.ready=not held and self.changed_at is not None and now-self.changed_at>=self.settle
        return self.ready
