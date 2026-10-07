"""Profile image crop dialog and model export preferences."""
import tkinter as tk
from tkinter import ttk,messagebox
from PIL import ImageTk

class CropDialog:
    def __init__(self,parent,image):
        self.image=image;self.result=None;self.start=None;self.box=None
        self.window=tk.Toplevel(parent);self.window.title('New zone profile - crop map image');self.window.transient(parent)
        ttk.Label(self.window,text='Name the zone, then drag a rectangle around it. Use whole image to skip cropping.').pack(padx=12,pady=8)
        self.name=tk.StringVar(value='My zone');ttk.Entry(self.window,textvariable=self.name).pack(fill='x',padx=12,pady=(0,8))
        self.scale=min(1,(parent.winfo_screenwidth()-120)/image.width,(parent.winfo_screenheight()-210)/image.height)
        self.photo=ImageTk.PhotoImage(image.resize((round(image.width*self.scale),round(image.height*self.scale))))
        self.canvas=tk.Canvas(self.window,width=self.photo.width(),height=self.photo.height(),highlightthickness=0);self.canvas.pack(padx=12)
        self.canvas.create_image(0,0,anchor='nw',image=self.photo);self.rect=None
        self.canvas.bind('<Button-1>',self.begin);self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',self.end)
        row=ttk.Frame(self.window);row.pack(fill='x',padx=12,pady=10)
        ttk.Button(row,text='Use selected crop',command=self.accept).pack(side='left',padx=4)
        ttk.Button(row,text='Use whole image',command=lambda:self.accept(True)).pack(side='left',padx=4)
        ttk.Button(row,text='Cancel',command=self.window.destroy).pack(side='right')
        self.window.grab_set();parent.wait_window(self.window)
    def point(self,e):return (max(0,min(self.image.width,round(e.x/self.scale))),max(0,min(self.image.height,round(e.y/self.scale))))
    def begin(self,e):
        self.start=self.point(e);self.box=None
        if self.rect:self.canvas.delete(self.rect)
        self.rect=self.canvas.create_rectangle(e.x,e.y,e.x,e.y,outline='#40dbf1',width=3)
    def drag(self,e):
        if self.start:
            x,y=self.point(e);self.canvas.coords(self.rect,self.start[0]*self.scale,self.start[1]*self.scale,x*self.scale,y*self.scale)
    def end(self,e):
        if self.start:
            x,y=self.point(e);sx,sy=self.start;self.box=(min(x,sx),min(y,sy),max(x,sx),max(y,sy));self.drag(e)
    def accept(self,whole=False):
        box=(0,0,*self.image.size) if whole else self.box
        if not box or box[2]-box[0]<80 or box[3]-box[1]<80:messagebox.showerror('Crop map','Select a crop at least 80 x 80 pixels.',parent=self.window);return
        self.result=(self.name.get().strip()[:100] or 'My zone',box);self.window.destroy()


class MapAreaDialog(CropDialog):
    """Choose a screen boundary; no profile picture or screenshot is stored."""
    def __init__(self,parent,image,previous=None):
        self.image=image;self.result=None;self.start=None;self.box=None
        self.window=tk.Toplevel(parent);self.window.title('Select minimap / floating map area');self.window.transient(parent)
        ttk.Label(self.window,text='Drag around the map terrain only. Exclude its title, sliders and buttons.\nIf the panel is translucent, increase its map opacity for more reliable tracking.',wraplength=900).pack(padx=12,pady=8)
        self.shape=tk.StringVar(value='Round' if previous and previous.get('shape')=='ellipse' else 'Rectangle')
        row=ttk.Frame(self.window);row.pack(fill='x',padx=12,pady=5)
        ttk.Label(row,text='Map shape:').pack(side='left');ttk.Combobox(row,textvariable=self.shape,values=['Rectangle','Round'],state='readonly',width=12).pack(side='left',padx=8)
        self.scale=min(1,(parent.winfo_screenwidth()-120)/image.width,(parent.winfo_screenheight()-220)/image.height)
        self.photo=ImageTk.PhotoImage(image.resize((round(image.width*self.scale),round(image.height*self.scale))))
        self.canvas=tk.Canvas(self.window,width=self.photo.width(),height=self.photo.height(),highlightthickness=0);self.canvas.pack(padx=12)
        self.canvas.create_image(0,0,anchor='nw',image=self.photo);self.rect=None
        if previous:
            l,t,r,b=previous['bounds'];self.box=(round(l*image.width),round(t*image.height),round(r*image.width),round(b*image.height))
            self.rect=self.canvas.create_rectangle(*(v*self.scale for v in self.box),outline='#40dbf1',width=3)
        self.canvas.bind('<Button-1>',self.begin);self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',self.end)
        row=ttk.Frame(self.window);row.pack(fill='x',padx=12,pady=10)
        ttk.Button(row,text='Use this map area',command=self.accept).pack(side='left')
        ttk.Button(row,text='Cancel',command=self.window.destroy).pack(side='right')
        self.window.grab_set();parent.wait_window(self.window)
    def accept(self,whole=False):
        box=self.box
        if not box or box[2]-box[0]<80 or box[3]-box[1]<80:messagebox.showerror('Map area','Select a map area at least 80 x 80 pixels.',parent=self.window);return
        l,t,r,b=box
        self.result=dict(bounds=[l/self.image.width,t/self.image.height,r/self.image.width,b/self.image.height],shape='ellipse' if self.shape.get()=='Round' else 'rectangle')
        self.window.destroy()


class IconSampleDialog(CropDialog):
    """Let the user select their own reference icon, enlarged for precision."""
    def __init__(self,parent,image,kind):
        self.image=image;self.result=None;self.start=None;self.box=None
        self.window=tk.Toplevel(parent);self.window.title('Learn '+kind+' icon');self.window.transient(parent)
        ttk.Label(self.window,text='Drag a tight rectangle around the resource icon. Include a small border.\nThis sample stays on your computer.',wraplength=500).pack(padx=12,pady=10)
        self.scale=4
        from PIL import Image
        self.photo=ImageTk.PhotoImage(image.resize((image.width*4,image.height*4),Image.Resampling.NEAREST))
        self.canvas=tk.Canvas(self.window,width=self.photo.width(),height=self.photo.height(),highlightthickness=0);self.canvas.pack(padx=12)
        self.canvas.create_image(0,0,anchor='nw',image=self.photo);self.rect=None
        self.canvas.bind('<Button-1>',self.begin);self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',self.end)
        row=ttk.Frame(self.window);row.pack(fill='x',padx=12,pady=10)
        ttk.Button(row,text='Learn selected icon',command=self.accept).pack(side='left')
        ttk.Button(row,text='Cancel',command=self.window.destroy).pack(side='right')
        self.window.grab_set();parent.wait_window(self.window)
    def accept(self,whole=False):
        if not self.box or not 6<=self.box[2]-self.box[0]<=64 or not 6<=self.box[3]-self.box[1]<=64:
            messagebox.showerror('Learn icon','Select a tight icon crop between 6 and 64 pixels across.',parent=self.window);return
        self.result=self.image.crop(self.box);self.window.destroy()
