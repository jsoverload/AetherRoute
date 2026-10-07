from security import ValidationError
from pathlib import Path
import base64
import io
import json
import math
import os
import queue
import sys
import threading
import time

import uuid
import zipfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import cv2
import numpy as np
from PIL import Image, ImageTk
from tracking import TerrainTracker, project, clip_map_segment, inside_map
from planner import best_route, length
from routes import REFERENCE, KINDS, NAMES, clean_nodes, decode_route, read_catalog, label, connect_nodes
from motion import MotionGate
from profiles import ProfileStore, load_image, image_bytes, profile_source
from profile_ui import CropDialog, MapAreaDialog, IconSampleDialog
from model_routes import context, prompt_for, accept_response
from map_visuals import COLORS, BG, FG, PANEL, ROUTE, model_image, resource_legend, legend_image
from ui_settings import Preferences
from icon_types import IconTypes, save_sample, import_samples
from product import NAME, VERSION, TAGLINE, DATA_FOLDER
from security import read_json, atomic_json, safe_image, friendly_error
from minimap import MinimapTracker, settings as minimap_settings

ROOT=Path(__file__).resolve().parent
KEY='#ff00ff'

def marker(canvas,x,y,kind,size=6,outline='#13202c'):
    color=COLORS[kind]
    if kind in ('Ore','HiddenCube'):
        canvas.create_rectangle(x-size,y-size,x+size,y+size,fill=color,outline=outline,width=2)
        if kind=='HiddenCube':canvas.create_text(x,y,text='C',fill='#13202c',font=('Segoe UI',7,'bold'))
    elif kind=='Crystal':canvas.create_polygon(x,y-size-2,x+size,y,x,y+size+2,x-size,y,fill=color,outline=outline,width=2)
    elif kind=='Plant':
        points=[]
        for j in range(10):
            angle=math.pi*j/5-math.pi/2;r=size+2 if j%2==0 else size*.45
            points.extend((x+math.cos(angle)*r,y+math.sin(angle)*r))
        canvas.create_polygon(*points,fill=color,outline=outline,width=2)
    else:
        canvas.create_oval(x-size,y-size,x+size,y+size,fill=color,outline=outline,width=2)
        canvas.create_text(x,y,text=NAMES[kind][0],fill='#13202c',font=('Segoe UI',7,'bold'))

class RouteEditor:
    def __init__(self, app):
        self.app=app;self.history=[];self.selected=None;self.icons=IconTypes(app.reference,user_templates=app.base_dir/'icon-types')
        self.window=tk.Toplevel(app.root);self.window.title('Edit route - '+app.route_name.get());self.window.configure(bg=BG)
        self.window.attributes('-topmost',app.preferences.data['main_topmost'])
        # Fit small crops as well as large maps; scaling is display-only.
        self.scale=min(max(80,min(1000,self.window.winfo_screenheight()-230))/app.reference.height,
                       max(80,min(1400,self.window.winfo_screenwidth()-280))/app.reference.width)
        self.width,self.height=round(app.reference.width*self.scale),round(app.reference.height*self.scale)
        toolbar=ttk.Frame(self.window);toolbar.pack(fill='x',padx=10,pady=8)
        self.kind=tk.StringVar(value='Custom');self.name=tk.StringVar()
        ttk.Label(toolbar,text='Type:').pack(side='left')
        ttk.Combobox(toolbar,textvariable=self.kind,values=list(NAMES.values()),width=12,state='readonly').pack(side='left',padx=4)
        ttk.Entry(toolbar,textvariable=self.name,width=20).pack(side='left',padx=4)
        ttk.Button(toolbar,text='Apply to selected',command=self.rename).pack(side='left',padx=4)
        ttk.Button(toolbar,text='Undo',command=self.undo).pack(side='left',padx=4)
        self.show_catalog=tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar,text='Catalog',variable=self.show_catalog,command=self.draw).pack(side='left',padx=4)
        options=ttk.Frame(self.window);options.pack(fill='x',padx=10,pady=4)
        self.auto_type=tk.BooleanVar(value=profile_source(app.profile)=='interactive' or bool(self.icons.templates))
        self.devtools=ttk.Frame(options)
        ttk.Checkbutton(self.devtools,text='Auto type from image',variable=self.auto_type).pack(side='left',padx=(0,12))
        ttk.Button(self.devtools,text='Learn icon',command=self.learn_icon).pack(side='left',padx=(0,12))
        ttk.Button(self.devtools,text='Import icons',command=self.import_icons).pack(side='left',padx=(0,12))
        self.refresh_developer_mode()
        ttk.Label(self.window,text='Click: select/add | Ctrl+click: manual | Right: remove | Shift: start').pack(anchor='w',padx=10,pady=(0,5))
        body=ttk.Frame(self.window);body.pack(fill='both',expand=True,padx=10)
        self.canvas=tk.Canvas(body,width=self.width,height=self.height,highlightthickness=0,bg=BG);self.canvas.pack(side='left')
        self.image=ImageTk.PhotoImage(app.reference.resize((self.width,self.height),Image.Resampling.BILINEAR))
        sidebar=ttk.Frame(body,width=200);sidebar.pack(side='left',fill='y',padx=(10,0))
        ttk.Button(sidebar,text='Connect all nodes',command=self.connect_all).pack(fill='x',pady=(0,8))
        ttk.Label(sidebar,text='Route order').pack(anchor='w')
        listframe=ttk.Frame(sidebar);listframe.pack(fill='both',expand=True)
        self.stops=tk.Listbox(listframe,width=24,bg=PANEL,fg=FG,selectbackground='#365f79',exportselection=False)
        self.stops.pack(side='left',fill='both',expand=True)
        scrollbar=ttk.Scrollbar(listframe,command=self.stops.yview);scrollbar.pack(side='left',fill='y');self.stops.configure(yscrollcommand=scrollbar.set)
        self.stops.bind('<<ListboxSelect>>',self.select)
        for text,command in [('Move up',lambda:self.move(-1)),('Move down',lambda:self.move(1)),('Remove stop',self.remove),('Shorten route',app.shorten)]:
            ttk.Button(sidebar,text=text,command=command).pack(fill='x',pady=3)
        self.hint=tk.StringVar(value='Click a resource icon to recognize its type. Ctrl+click uses your chosen type/name.')
        if profile_source(app.profile)=='interactive':self.hint.set('Click a resource to add its exact database type. Ctrl+click adds a manual stop.')
        elif not app.developer_mode.get() and not self.icons.templates:self.hint.set('Picture zone: choose Type, then click to add a stop. Add custom icon samples in Developer mode to enable automatic typing.')
        elif not self.icons.templates:self.hint.set('Select a stop, choose its Type, then Learn icon to enable automatic typing.')
        ttk.Label(self.window,textvariable=self.hint,wraplength=950).pack(fill='x',padx=10,pady=8)
        self.canvas.bind('<Button-1>',self.edit);self.canvas.bind('<Button-3>',self.edit);self.canvas.bind('<Motion>',self.hover)
        self.draw();self.window.protocol('WM_DELETE_WINDOW',self.close)
    def refresh_developer_mode(self):
        if self.app.developer_mode.get():self.devtools.pack(side='left')
        else:self.devtools.pack_forget()
    def visible_catalog(self):
        return [n for n in self.app.catalog if n['Kind'] not in self.app.filters or self.app.filters[n['Kind']].get()]
    def connect_all(self):
        try:nodes=connect_nodes(self.app.nodes,self.visible_catalog())
        except ValidationError as exc:
            messagebox.showinfo('Connect all nodes',str(exc),parent=self.window);return
        added=len(nodes)-len(self.app.nodes)
        if not added:
            self.hint.set('All selected resources are already connected. Use Shorten route to adjust their order.' if nodes else 'No resource nodes are available. Select resource types or add stops to this zone.');return
        self.remember();self.app.nodes=nodes;self.selected=None;self.app.next_node=0
        self.app.route_changed()
        self.hint.set(f'Connected {added:,} additional nodes. Existing stops kept their order. Undo reverses this action; Shorten route can reduce map distance.')
    def learn_icon(self):
        if self.selected is None or self.selected>=len(self.app.nodes):
            messagebox.showinfo('Learn icon','Click a resource icon to add or select a stop first.',parent=self.window);return
        try:
            kind=next(k for k,v in NAMES.items() if v==self.kind.get())
            if kind in ('Custom','Waypoint'):raise ValidationError('Choose the resource Type first, then click Learn icon.')
            node=self.app.nodes[self.selected];x,y=round(node['X']),round(node['Y']);im=self.app.reference
            sample=im.crop((max(0,x-48),max(0,y-48),min(im.width,x+48),min(im.height,y+48)))
            dialog=IconSampleDialog(self.window,sample,NAMES[kind])
            if dialog.result is None:return
            save_sample(dialog.result,kind,self.app.base_dir/'icon-types')
            self.icons=IconTypes(im,user_templates=self.app.base_dir/'icon-types');self.rename()
            self.auto_type.set(True)
            self.hint.set('Learned '+NAMES[kind]+'. Click another matching icon to use automatic typing.')
        except (ValueError,OSError) as exc:messagebox.showerror('Learn icon',friendly_error(exc),parent=self.window)
    def import_icons(self):
        folder=filedialog.askdirectory(parent=self.window,title='Choose your icon samples folder')
        if not folder:return
        try:
            count=import_samples(folder,self.app.base_dir/'icon-types')
            self.icons=IconTypes(self.app.reference,user_templates=self.app.base_dir/'icon-types')
            if count:self.auto_type.set(True)
            self.hint.set(str(count)+' icon samples imported locally. Automatic typing is ready.')
        except (ValueError,OSError) as exc:messagebox.showerror('Import icons',friendly_error(exc),parent=self.window)
    def remember(self):
        self.history.append([dict(n) for n in self.app.nodes]);self.history=self.history[-30:]
    def select(self,event=None):
        indices=self.stops.curselection()
        if indices:self.select_stop(indices[0])
    def select_stop(self,index):
        # Map clicks set the index directly. Redrawing the listbox can emit an
        # empty selection event; it must not erase the just-selected type.
        self.selected=index
        if index is not None and 0<=index<len(self.app.nodes):
            n=self.app.nodes[index];self.kind.set(NAMES[n['Kind']]);self.name.set(n.get('Name',''))
            self.hint.set(f"{label(n)} | {NAMES[n['Kind']]} | {n.get('Source','Manual marker')}")
        self.draw()
    def move(self,direction):
        if self.selected is None:return
        at=self.selected;to=at+direction
        if not 0<=to<len(self.app.nodes):return
        self.remember();self.app.nodes[at],self.app.nodes[to]=self.app.nodes[to],self.app.nodes[at];self.selected=to;self.app.next_node=0;self.app.route_changed()
    def remove(self):
        if self.selected is None or self.selected>=len(self.app.nodes):return
        self.remember();self.app.nodes.pop(self.selected);self.selected=None;self.app.route_changed()
    def rename(self):
        if self.selected is None or self.selected>=len(self.app.nodes):return
        self.remember();n=self.app.nodes[self.selected];n['Kind']=next(k for k,v in NAMES.items() if v==self.kind.get());n['Name']=self.name.get().strip()[:240];n['Source']='Manual marker';self.app.route_changed()
    def nearest(self,x,y,nodes,radius=None):
        near=min(nodes,key=lambda n:(n['X']-x)**2+(n['Y']-y)**2,default=None)
        return near if near and math.hypot(near['X']-x,near['Y']-y)<(20/self.scale if radius is None else radius) else None
    def edit(self,event):
        x,y=event.x/self.scale,event.y/self.scale
        if not 0<=x<self.app.reference.width or not 0<=y<self.app.reference.height:return
        selecting=bool(event.state&1);manual=bool(event.state&4) and event.num==1 and not selecting
        if event.num==3 or selecting:
            near=self.nearest(x,y,self.app.active_nodes())
            if near is None:return
            self.remember()
            if event.num==3:self.app.nodes.remove(near)
            else:
                at=next(i for i,n in enumerate(self.app.nodes) if n is near);self.app.nodes=self.app.nodes[at:]+self.app.nodes[:at]
            self.selected=None;self.app.next_node=0;self.app.route_changed();return
        automatic=self.auto_type.get() and not manual
        database_nodes=[n for n in self.visible_catalog() if n.get('Source')=='Imported map database']
        database_match=self.nearest(x,y,database_nodes,10/self.scale) if automatic else None
        guess=self.icons.identify(x,y) if automatic and database_match is None and (profile_source(self.app.profile)!='interactive' or self.app.developer_mode.get()) else None
        sx,sy=(guess['X'],guess['Y']) if guess else (x,y)
        # Dense maps contain icons less than 20 px apart. Match the clicked
        # sprite's category before snapping, rather than stealing its neighbor.
        def eligible(nodes):
            return [n for n in nodes if not guess or n['Kind'] in (guess['Kind'],'Custom') or (not n.get('Name') and not n.get('Source'))]
        radius=9 if guess else 10/self.scale
        if database_match:
            # A nearby visited resource must not steal the clicked database ID.
            near=next((n for n in self.app.nodes if n.get('Id')==database_match.get('Id') and n.get('Id')),None)
            if near is None:near=next((n for n in self.app.nodes if n['X']==database_match['X'] and n['Y']==database_match['Y'] and n['Kind']==database_match['Kind']),None)
        else:near=None if manual else self.nearest(sx,sy,eligible(self.app.active_nodes()),radius)
        if near is not None:
            if guess and near['Kind']!=guess['Kind'] and ((near['Kind']=='Custom' and near.get('Source')!='Manual marker') or (not near.get('Name') and not near.get('Source'))):
                self.remember();near['Kind']=guess['Kind'];near['Source']=guess['Source'];self.app.route_changed()
            self.select_stop(next(i for i,n in enumerate(self.app.nodes) if n is near));return
        catalog_nodes=[n for n in self.visible_catalog() if not guess or n['Kind'] in (guess['Kind'],'Custom')]
        catalog=None if manual else database_match or self.nearest(sx,sy,catalog_nodes,radius)
        if catalog:
            existing=next((n for n in self.app.nodes if n['X']==catalog['X'] and n['Y']==catalog['Y'] and n['Kind']==catalog['Kind']),None)
            if existing is not None:self.select_stop(self.app.nodes.index(existing));return
        if len(self.app.nodes)>=1000:return
        self.remember()
        if catalog:
            node=dict(catalog)
            if guess and node['Kind']=='Custom' and node.get('Source')!='Manual marker':node.update(Kind=guess['Kind'],Source=guess['Source'])
        elif guess:node=dict(guess)
        elif automatic:
            # An unknown image icon must not inherit the last clicked type/name.
            node=dict(X=x,Y=y,Kind='Custom')
        else:
            kind=next(k for k,v in NAMES.items() if v==self.kind.get())
            node=dict(X=x,Y=y,Kind=kind,Name=self.name.get().strip()[:240],Source='Manual marker')
        self.app.nodes.append(node);self.app.next_node=0
        self.selected=len(self.app.nodes)-1;self.app.route_changed();self.select_stop(self.selected)
        if automatic and not catalog and not guess:self.hint.set('No confident icon match. Added Custom; choose its type and Apply to selected, or use Ctrl+click for manual points.')
    def hover(self,event):
        nodes=self.app.active_nodes()+(self.visible_catalog() if self.show_catalog.get() else [])
        n=self.nearest(event.x/self.scale,event.y/self.scale,nodes)
        if n:self.hint.set(f"{label(n)} | {NAMES[n['Kind']]} | {n.get('Source','Manual marker')} | X {n['X']:.1f}, Y {n['Y']:.1f}")
    def undo(self):
        if self.history:self.app.nodes=self.history.pop();self.selected=None;self.app.next_node=0;self.app.route_changed()
    def draw(self):
        self.canvas.delete('all');self.canvas.create_image(0,0,anchor='nw',image=self.image)
        if self.show_catalog.get():
            for n in self.visible_catalog():
                x,y=n['X']*self.scale,n['Y']*self.scale
                marker(self.canvas,x,y,n['Kind'],size=5)
        nodes=self.app.active_nodes()
        for a,b in self.app.edges(nodes):self.canvas.create_line(a['X']*self.scale,a['Y']*self.scale,b['X']*self.scale,b['Y']*self.scale,fill=ROUTE,width=2)
        for i,n in enumerate(nodes):
            x,y=n['X']*self.scale,n['Y']*self.scale;marker(self.canvas,x,y,n['Kind'])
            if i==self.app.next_node:self.canvas.create_oval(x-10,y-10,x+10,y+10,outline='#f2d65d',width=2)
            if self.selected is not None and self.selected<len(self.app.nodes) and n is self.app.nodes[self.selected]:self.canvas.create_rectangle(x-12,y-12,x+12,y+12,outline='#f5fbff',width=2)
        self.stops.delete(0,'end')
        for i,n in enumerate(self.app.nodes):self.stops.insert('end',f"{i+1}. {label(n)}")
        if self.selected is not None and self.selected<len(self.app.nodes):
            self.stops.selection_set(self.selected);self.stops.see(self.selected)
    def close(self):self.app.editor=None;self.window.destroy()

class App:
    def __init__(self,root,demo=None):
        self.root=root;self.demo=demo
        self.base_dir=Path(os.environ.get('LOCALAPPDATA',Path.home()))/DATA_FOLDER
        self.resource_root=ROOT;self.preferences=Preferences(self.base_dir)
        self.developer_mode=tk.BooleanVar(value=self.preferences.data['developer_mode'])
        self.profile_group=tk.StringVar(value='interactive')
        self.active_zone_text=tk.StringVar();self.profile_entries=[];self.hidden_windows=[];self.launcher=None
        self.store=ProfileStore(self.base_dir,ROOT/'assets');self.profile=self.store.active
        self.reference=load_image(self.store.image_path(self.profile));self.ref_id=self.profile['reference']
        self.nodes=[];self.catalog=self.profile['catalog'];self.saved_routes=self.profile['routes']
        self.route_id=str(uuid.uuid4());self.motion=MotionGate();self.last_sample=0
        self.next_node=0;self.editor=None;self.target=None;self.bound_region=None;self.client_geometry=None
        self.map_browser=None
        self.paused=False;self.closing=False;self.busy=False;self.generation=0
        self.last=None;self.last_bounds=None;self.last_shape='rectangle';self.last_capture=0;self.last_completed=0;self.capture_interval=.25;self.focused=False;self.recent_keys={}
        self.jobs=queue.Queue(maxsize=1);self.results=queue.Queue();self.calculations=queue.Queue();self.calculating=False
        self.cancel_calculation=threading.Event();self.calculation_worker=None
        self.root.title(NAME+' '+VERSION);self.root.configure(bg=BG)
        self.root.geometry(f'500x{max(640,min(960,self.root.winfo_screenheight()-80))}')
        self.root.minsize(500,640)
        style=ttk.Style();style.theme_use('clam')
        style.configure('.',background=BG,foreground=FG,font=('Segoe UI',10))
        style.configure('TButton',background=PANEL,foreground=FG,padding=7)
        style.map('TButton',background=[('active','#36465f')])
        style.configure('TCheckbutton',background=BG,foreground=FG)
        style.configure('TCombobox',fieldbackground=PANEL,foreground=FG)
        style.map('TCombobox',fieldbackground=[('readonly',PANEL)],foreground=[('readonly',FG)],selectbackground=[('readonly',PANEL)],selectforeground=[('readonly',FG)])
        style.configure('TEntry',fieldbackground=PANEL,foreground=FG)
        style.configure('TScale',background=BG,troughcolor=PANEL)
        style.configure('TNotebook',background=BG,bordercolor=PANEL)
        style.configure('TNotebook.Tab',background=PANEL,foreground=FG,padding=(9,5))
        style.map('TNotebook.Tab',background=[('selected','#34506a')],foreground=[('selected',FG)])
        self.filters={kind:tk.BooleanVar(value=True) for kind in KINDS if kind!='Waypoint'}
        self.route_name=tk.StringVar(value='Starter route');self.hide_moving=tk.BooleanVar(value=True)
        self.labels=tk.BooleanVar(value=True);self.loop=tk.BooleanVar(value=True);self.opacity=tk.DoubleVar(value=.85)
        self.status=tk.StringVar(value='Choose Bind game, then switch to Aion 2 within 3 seconds.')
        self.detail=tk.StringVar(value='Choose a zone profile and saved route.')
        self.progress=tk.StringVar()
        self.overlay_mode=tk.StringVar(value='Big map')
        self.minimap_info=tk.StringVar();self.restore_overlay_preferences()
        self.build_ui()
        self.load_session();self.refresh_library();self.refresh_profiles();self.load_model_preferences()
        self.overlay=tk.Toplevel(root);self.overlay.withdraw();self.overlay.overrideredirect(True)
        self.overlay.configure(bg=KEY);self.overlay.attributes('-topmost',True)
        if sys.platform=='win32':
            from windows import overlay_styles
            self.overlay.attributes('-transparentcolor',KEY)
        self.canvas=tk.Canvas(self.overlay,bg=KEY,highlightthickness=0,bd=0);self.canvas.pack(fill='both',expand=True)
        self.overlay.update_idletasks()
        self.capture_excluded=False
        if sys.platform=='win32':
            self.capture_excluded=overlay_styles(self.overlay)
            import mss
            self.capture=mss.MSS()
        self.root.report_callback_exception=lambda kind,exc,tb:messagebox.showerror(NAME,friendly_error(exc),parent=self.root)
        self.root.protocol('WM_DELETE_WINDOW',self.hide_main)
        self.root.bind('<Map>',lambda event:self.restore_hidden_windows() if event.widget is self.root and self.root.state()=='normal' else None)
        self.root.attributes('-topmost',self.preferences.data['main_topmost'])
        self.root.bind('<Escape>',lambda event:self.hide_main() if event.widget is self.root else None)
        self.route_changed(save=False)
        self.worker=threading.Thread(target=self.work,daemon=True);self.worker.start()
        if demo:
            frame=cv2.imread(str(demo))
            if frame is None:raise ValidationError('Demo frame is unreadable.')
            self.jobs.put((frame,time.perf_counter(),self.generation,dict(left=0,top=0,width=frame.shape[1],height=frame.shape[0]),self.tracker_spec()))
            self.busy=True;self.status.set('Analyzing recording frame - preview mode')
        self.root.after(30,self.tick)
        from desktop_ui import GameLauncher
        self.launcher=GameLauncher(self)
        if self.store.recovered:self.root.after(150,lambda:messagebox.showinfo(NAME,'Recovered your saved profiles from the local backup. The damaged file was kept for recovery.',parent=self.root))

    def build_ui(self):
        layout=ttk.Frame(self.root);layout.pack(fill='both',expand=True)
        footer=ttk.Frame(layout,padding=(10,6));footer.pack(side='bottom',fill='x')
        for text,command in [('Settings',self.open_settings),('Hide to launcher',self.hide_main),('Quit',self.close)]:
            ttk.Button(footer,text=text,command=command).pack(side='left',expand=True,fill='x',padx=2)
        scroll=ttk.Scrollbar(layout,orient='vertical');scroll.pack(side='right',fill='y')
        viewport=tk.Canvas(layout,bg=BG,highlightthickness=0,yscrollcommand=scroll.set);viewport.pack(side='left',fill='both',expand=True)
        scroll.configure(command=viewport.yview)
        box=ttk.Frame(viewport,padding=14);panel=viewport.create_window(0,0,anchor='nw',window=box)
        box.bind('<Configure>',lambda e:viewport.configure(scrollregion=viewport.bbox('all')))
        viewport.bind('<Configure>',lambda e:viewport.itemconfigure(panel,width=e.width))
        ttk.Label(box,text=NAME.upper(),font=('Segoe UI',17,'bold')).pack(anchor='w')
        ttk.Label(box,text=TAGLINE,foreground='#b7c5d8').pack(anchor='w')
        row=ttk.Frame(box);row.pack(fill='x',pady=(10,3))
        for text,value in [('Interactive map zones','interactive'),('Picture zones','picture')]:
            ttk.Radiobutton(row,text=text,variable=self.profile_group,value=value,command=lambda:self.refresh_profiles(False)).pack(side='left',padx=(0,10))
        self.profile_selector=ttk.Combobox(box,state='readonly');self.profile_selector.pack(fill='x');self.profile_selector.bind('<<ComboboxSelected>>',self.switch_profile)
        ttk.Label(box,textvariable=self.active_zone_text,wraplength=445,foreground='#b7c5d8').pack(anchor='w',pady=3)
        row=ttk.Frame(box);row.pack(fill='x',pady=6)
        for text,command in [('Interactive maps',self.open_map_browser),('New zone / picture',self.new_profile)]:ttk.Button(row,text=text,command=command).pack(side='left',expand=True,fill='x',padx=2)
        row=ttk.Frame(box);row.pack(fill='x',pady=(0,4))
        for text,command in [('Import profile',self.import_profile),('Export profile',self.export_profile)]:ttk.Button(row,text=text,command=command).pack(side='left',expand=True,fill='x',padx=2)
        row=ttk.Frame(box);row.pack(fill='x',pady=(0,4))
        for text,command in [('Crop this zone',self.crop_profile),('Rename zone',self.rename_profile),('Delete zone',self.delete_profile)]:ttk.Button(row,text=text,command=command).pack(side='left',expand=True,fill='x',padx=2)
        tabs=ttk.Notebook(box);tabs.pack(fill='both',expand=True,pady=6)
        routes=ttk.Frame(tabs,padding=10);overlay=ttk.Frame(tabs,padding=10);planning=ttk.Frame(tabs,padding=10)
        tabs.add(routes,text='Routes');tabs.add(overlay,text='Overlay');tabs.add(planning,text='Model planning')
        ttk.Label(routes,text='Saved routes in this zone').pack(anchor='w')
        self.route_selector=ttk.Combobox(routes,state='readonly');self.route_selector.pack(fill='x',pady=5);self.route_selector.bind('<<ComboboxSelected>>',self.switch_route)
        ttk.Label(routes,text='Route name').pack(anchor='w')
        entry=ttk.Entry(routes,textvariable=self.route_name);entry.pack(fill='x',pady=(3,8));entry.bind('<FocusOut>',lambda e:self.route_changed());entry.bind('<Return>',lambda e:self.route_changed())
        for buttons in [[('New route',self.new_route),('Edit route',self.open_editor)],[('Import route',self.load_route),('Export route',self.save_route)],[('Save route',self.store_route),('Delete route',self.delete_route)],[('Connect all nodes',self.connect_all),('Calculate shortest',self.shorten)]]:
            row=ttk.Frame(routes);row.pack(fill='x',pady=3)
            for text,command in buttons:ttk.Button(row,text=text,command=command).pack(side='left',expand=True,fill='x',padx=2)
        self.route_devtools=ttk.Frame(routes)
        ttk.Button(self.route_devtools,text='Import custom catalog',command=self.import_catalog).pack(fill='x')
        if self.developer_mode.get():self.route_devtools.pack(fill='x',pady=3)
        ttk.Label(routes,text='Changes save automatically. New routes keep the current one.\nDelete route asks twice.',wraplength=420,foreground='#b7c5d8').pack(anchor='w',pady=10)
        ttk.Label(routes,text='Include these marker types').pack(anchor='w')
        row=ttk.Frame(routes);row.pack(fill='x',pady=5)
        for i,kind in enumerate(self.filters):ttk.Checkbutton(row,text=NAMES[kind],variable=self.filters[kind],command=self.route_changed).grid(row=i//3,column=i%3,sticky='w',padx=(0,9),pady=1)
        row=ttk.Frame(routes);row.pack(fill='x',pady=6)
        ttk.Checkbutton(row,text='Item/type labels',variable=self.labels,command=self.route_changed).pack(side='left')
        ttk.Checkbutton(row,text='Loop',variable=self.loop,command=self.route_changed).pack(side='left',padx=18)
        ttk.Button(overlay,text='Bind game - switch to Aion 2 in 3 seconds',command=self.bind).pack(fill='x')
        ttk.Label(overlay,text='Track this map').pack(anchor='w',pady=(8,0))
        mode=ttk.Combobox(overlay,textvariable=self.overlay_mode,values=['Big map','Minimap / floating map'],state='readonly');mode.pack(fill='x',pady=4);mode.bind('<<ComboboxSelected>>',self.change_overlay_mode)
        ttk.Button(overlay,text='Set minimap area - switch to game in 3 seconds',command=self.choose_minimap_area).pack(fill='x',pady=3)
        ttk.Label(overlay,textvariable=self.minimap_info,wraplength=410,foreground='#b7c5d8').pack(anchor='w',pady=3)
        self.pause_button=ttk.Button(overlay,text='Pause tracking',command=self.toggle_pause);self.pause_button.pack(fill='x',pady=6)
        ttk.Checkbutton(overlay,text='Hide while big map moves (recommended)',variable=self.hide_moving,command=self.route_changed).pack(anchor='w',pady=8)
        ttk.Label(overlay,text='Opacity').pack(anchor='w');ttk.Scale(overlay,from_=.25,to=1,variable=self.opacity,command=self.opacity_changed).pack(fill='x',pady=5)
        ttk.Label(overlay,text='Minimap: bind game, show the panel, then Set minimap area. Choose its terrain interior. Routes stay inside that area and track while you move. Re-select after moving/resizing the panel.\n\nUse high map opacity. Transparent terrain or a different zone can lose alignment. Only the current stop is labeled in minimap mode.',wraplength=420,foreground='#b7c5d8').pack(anchor='w',pady=10)
        self.plan_mode=tk.StringVar(value='Order existing stops')
        ttk.Label(planning,text='Planning mode').pack(anchor='w')
        ttk.Combobox(planning,state='readonly',textvariable=self.plan_mode,values=['Order existing stops','Draw path from image']).pack(fill='x',pady=5)
        self.plan_source=tk.StringVar(value='Current route')
        ttk.Label(planning,text='Known stops to include (optional in image mode)').pack(anchor='w')
        ttk.Combobox(planning,state='readonly',textvariable=self.plan_source,values=['Current route','Filtered catalog']).pack(fill='x',pady=5)
        self.plan_subset=tk.BooleanVar(value=False)
        ttk.Checkbutton(planning,text='Allow model to choose a subset of stops',variable=self.plan_subset).pack(anchor='w',pady=5)
        ttk.Label(planning,text='Your custom prompt / preferences').pack(anchor='w')
        self.plan_prompt=tk.Text(planning,height=5,bg=PANEL,fg=FG,insertbackground=FG,wrap='word');self.plan_prompt.pack(fill='x',pady=5)
        self.plan_prompt.insert('1.0','Prioritize a short loop. Keep collection order practical.')
        ttk.Button(planning,text='Export model pack (image + JSON)',command=self.export_model_task).pack(fill='x',pady=3)
        ttk.Button(planning,text='Import model response JSON',command=self.import_model_plan).pack(fill='x',pady=3)
        ttk.Label(planning,text='Filtered resources appear in the exported picture even without a route. Extract the pack, attach map.png, legend.png and task.json to your vision model, and use PROMPT.txt. Image mode can choose resources and add waypoints around terrain. Import opens a new editable route. Review image estimates. No model runs automatically inside this app.',wraplength=420,foreground='#b7c5d8').pack(anchor='w',pady=10)
        ttk.Label(box,textvariable=self.status,wraplength=450).pack(anchor='w',pady=(6,2))
        ttk.Label(box,textvariable=self.detail,wraplength=450,foreground='#b7c5d8').pack(anchor='w',pady=2)
        row=ttk.Frame(box);row.pack(fill='x',pady=5)
        ttk.Button(row,text='Previous',command=lambda:self.advance(-1)).pack(side='left',expand=True,fill='x');ttk.Button(row,text='Next node',command=lambda:self.advance(1)).pack(side='left',expand=True,fill='x',padx=(8,0))
        ttk.Label(box,textvariable=self.progress,wraplength=450).pack(anchor='w',pady=3)
        ttk.Label(box,text='Ctrl+Alt+Space: pause | Ctrl+Alt+N / P: node',font=('Segoe UI',9),foreground='#b7c5d8').pack(anchor='w')

    def open_settings(self):
        from desktop_ui import SettingsDialog
        SettingsDialog(self)
    def apply_preferences(self,**changes):
        self.preferences.update(**changes)
        self.developer_mode.set(self.preferences.data['developer_mode'])
        self.root.attributes('-topmost',self.preferences.data['main_topmost'])
        if self.developer_mode.get():self.route_devtools.pack(fill='x',pady=3)
        else:self.route_devtools.pack_forget()
        if self.editor:self.editor.refresh_developer_mode()
        if self.map_browser:self.map_browser.refresh_developer_mode()
        for item in (self.editor,self.map_browser):
            if item:item.window.attributes('-topmost',self.preferences.data['main_topmost'])
        if self.launcher:self.launcher.sync()
    def show_main(self):
        self.root.deiconify();self.root.lift();self.root.focus_force()
        self.restore_hidden_windows()
    def restore_hidden_windows(self):
        windows=self.hidden_windows;self.hidden_windows=[]
        for window in windows:
            if window.winfo_exists():window.deiconify()
        if self.launcher:self.launcher.sync()
    def hide_main(self):
        if self.closing or not self.store_route():return
        for item in (self.editor,self.map_browser):
            if item and item.window.winfo_exists() and item.window.state()!='withdrawn':
                self.hidden_windows.append(item.window);item.window.withdraw()
        if not self.preferences.data['launcher_enabled']:
            self.root.iconify();return
        self.root.withdraw()
        if sys.platform=='win32' and self.target:
            from windows import activate_window
            activate_window(self.target)
        if self.launcher:self.launcher.sync()
    def capture_frame(self,region):
        launcher=self.launcher
        hidden=launcher and not launcher.capture_excluded
        if hidden:launcher.window.withdraw();self.root.update_idletasks()
        try:return np.asarray(self.capture.grab(region))[:,:,:3].copy()
        finally:
            if hidden:launcher.sync()
    def active_nodes(self):return [n for n in self.nodes if n['Kind'] not in self.filters or self.filters[n['Kind']].get()]
    def edges(self,nodes):
        edges=list(zip(nodes,nodes[1:]))
        if self.loop.get() and len(nodes)>1:edges.append((nodes[-1],nodes[0]))
        return edges
    def advance(self,direction):
        self.next_node=max(0,min(max(0,len(self.active_nodes())-1),self.next_node+direction));self.route_changed()
    def opacity_changed(self,value=None):
        if hasattr(self,'overlay'):self.overlay.attributes('-alpha',self.opacity.get())
    def route_changed(self,save=True):
        active=self.active_nodes();self.next_node=max(0,min(max(0,len(active)-1),self.next_node))
        current=label(active[self.next_node]) if active else 'Empty route'
        self.progress.set(f'{current} | Stop {self.next_node+1 if active else 0} / {len(active)} | {len(self.nodes)} total')
        if self.editor:self.editor.draw()
        if self.last is not None and (not self.hide_for_motion() or self.motion.ready or self.demo):self.draw(self.last)
        if save:self.save_session()
    def open_editor(self):
        if self.editor:self.editor.window.lift()
        else:self.editor=RouteEditor(self)
    def connect_all(self):
        self.open_editor();self.editor.connect_all()
    def shorten(self):
        if self.calculating:self.detail.set('A route calculation is already running.');return
        nodes=self.active_nodes()
        if any(n['Kind']=='Waypoint' for n in nodes):self.detail.set('This path has navigation waypoints. Replan with the model to preserve its bends.');return
        if len(nodes)<2:self.detail.set('Add at least two stops before calculating a route.');return
        snapshot=json.dumps(dict(nodes=self.nodes,filters={k:v.get() for k,v in self.filters.items()}),sort_keys=True);route_id=self.route_id;profile_id=self.profile['id'];loop=self.loop.get()
        active=[dict(n) for n in nodes];inactive=[dict(n) for n in self.nodes if n not in nodes]
        self.calculating=True;self.cancel_calculation.clear();self.detail.set(f'Calculating {len(active)} stops... You can keep using the overlay.')
        def calculate():
            try:
                ordered,exact=best_route(active,loop,cancel=self.cancel_calculation.is_set);self.calculations.put((profile_id,route_id,snapshot,loop,ordered,inactive,exact,None))
            except Exception as exc:self.calculations.put((profile_id,route_id,snapshot,loop,None,inactive,False,friendly_error(exc)))
        self.calculation_worker=threading.Thread(target=calculate,daemon=True);self.calculation_worker.start()
    def calculation_results(self):
        try:profile_id,route_id,snapshot,loop,ordered,inactive,exact,error=self.calculations.get_nowait()
        except queue.Empty:return
        self.calculating=False
        if profile_id!=self.profile['id'] or route_id!=self.route_id or snapshot!=json.dumps(dict(nodes=self.nodes,filters={k:v.get() for k,v in self.filters.items()}),sort_keys=True) or loop!=self.loop.get():
            self.detail.set('Route changed during calculation. Calculate again to use the new stops.');return
        if error:self.detail.set('Route calculation failed: '+error);return
        before=length(self.active_nodes(),loop)
        if self.editor:self.editor.remember()
        self.nodes=ordered+inactive;self.next_node=0;self.route_changed()
        after=length(ordered,loop);self.detail.set(f"{'Exact shortest' if exact else 'Heuristic route'}: {after:.0f} map px, {100*(1-after/before) if before else 0:.1f}% shorter. Travel barriers are not modeled.")
    def bind(self):
        if self.demo:return
        self.status.set('Switch to your Aion 2 window now - binding in 3 seconds.')
        self.root.after(3000,self.finish_bind)
    def finish_bind(self):
        from windows import foreground,client_region,title,root_handle
        target=foreground()
        own_windows=[self.root]+[w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel)]
        if target in {root_handle(w) for w in own_windows} or client_region(target) is None:
            self.status.set('Binding failed. Click Bind game and switch to Aion 2 before the countdown ends.');return
        self.target=target;self.motion.reset();self.generation+=1;self.last=None;self.overlay.withdraw()
        self.detail.set('Bound to '+title(target));self.status.set('Open your map with M. Tracking will start when terrain matches.')
    def toggle_pause(self):
        self.paused=not self.paused;self.motion.reset();self.generation+=1;self.last=None;self.overlay.withdraw()
        self.pause_button.configure(text='Resume tracking' if self.paused else 'Pause tracking')
        self.status.set('Tracking paused' if self.paused else 'Waiting for visible map terrain')
    def work(self):
        tracker=None;spec=None
        while not self.closing:
            try:frame,stamp,generation,region,requested=self.jobs.get(timeout=.2)
            except queue.Empty:continue
            try:
                if tracker is None or requested!=spec:
                    mode=requested[2] if len(requested)>2 else 'big'
                    config=dict(bounds=requested[3],shape=requested[4]) if mode=='minimap' and requested[3] is not None else None
                    tracker=MinimapTracker(ROOT/'assets',requested[0],config) if mode=='minimap' else TerrainTracker(ROOT/'assets',reference_path=requested[0],use_header=requested[1])
                    spec=requested
                result=tracker.register(frame,timestamp=stamp)
                self.results.put((result,stamp,generation,region,None))
            except Exception:
                tracker=None;spec=None
                self.results.put((None,stamp,generation,region,friendly_error(sys.exc_info()[1])))
    def poll_keys(self):
        from windows import key_down
        ctrl_alt=key_down(0x11) and key_down(0x12)
        actions={0x20:self.toggle_pause,0x4e:lambda:self.advance(1),0x50:lambda:self.advance(-1)}
        for key,action in actions.items():
            pressed=ctrl_alt and key_down(key)
            if pressed and not self.recent_keys.get(key,False):action()
            self.recent_keys[key]=pressed
        if self.hide_for_motion() and any(key_down(k) for k in (1,2,4)):
            self.motion.hold(time.perf_counter());self.last=None;self.overlay.withdraw()
        for key in (0x4d,0x1b):
            pressed=key_down(key) and not ctrl_alt
            if pressed and not self.recent_keys.get(key,False):
                self.motion.reset();self.generation+=1;self.last=None;self.last_completed=0;self.overlay.withdraw()
            self.recent_keys[key]=pressed
    def tick(self):
        if self.closing:return
        now=time.perf_counter();self.calculation_results()
        if not self.demo:
            from windows import foreground,client_region
            focused=self.target is not None and foreground()==self.target
            if focused!=self.focused:
                self.motion.reset();self.generation+=1;self.last=None;self.overlay.withdraw();self.focused=focused
            if focused:
                self.poll_keys()
                current_geometry=client_region(self.target)
                if current_geometry!=self.client_geometry:
                    self.client_geometry=current_geometry;self.motion.reset();self.generation+=1
                    self.last=None;self.overlay.withdraw()
            if not focused or self.paused:self.overlay.withdraw()
            if self.last is not None and now-self.last_capture>.4:self.last=None;self.overlay.withdraw()
        while True:
            try:result,stamp,generation,region,error=self.results.get_nowait()
            except queue.Empty:break
            self.busy=False
            if generation!=self.generation:continue
            if error:
                self.status.set('Tracking error - '+error.splitlines()[-1]);self.paused=True;self.pause_button.configure(text='Resume tracking');self.overlay.withdraw();continue
            if generation!=self.generation or (not self.demo and now-stamp>.4):continue
            if not self.demo and (not self.focused or self.paused or (self.hide_for_motion() and (not self.motion.ready or stamp<self.motion.changed_at))):continue
            self.status.set('Route aligned - map settled' if result.matrix is not None and self.hide_for_motion() else result.status)
            self.capture_interval=.055 if self.is_minimap() or result.header_score>=.78 else .25
            self.last_capture=stamp;self.bound_region=region;self.last_bounds=result.bounds;self.last_shape=result.shape
            if result.matrix is None:self.last=None;self.overlay.withdraw()
            else:
                self.last=result.matrix;self.draw(result.matrix)
                self.detail.set(f'{len(self.catalog)} catalog markers | Alignment confirmed')
        if not self.demo and self.target and self.focused and not self.paused and now-self.last_sample>.05:
            from windows import client_region,key_down
            region=client_region(self.target)
            if region:
                self.opacity_changed()
                if not self.capture_excluded:self.overlay.withdraw();self.root.update_idletasks()
                try:
                    frame=self.capture_frame(region);self.last_sample=now
                    was_ready=self.motion.ready
                    ready=self.motion.update(frame,now,held=any(key_down(k) for k in (1,2,4)))
                    if self.hide_for_motion() and not ready:
                        if was_ready:self.generation+=1
                        self.last=None;self.overlay.withdraw();self.status.set('Map moving / settling - route hidden')
                    elif not self.busy and now-self.last_completed>self.capture_interval:
                        self.jobs.put_nowait((frame,now,self.generation,region,self.tracker_spec()));self.busy=True;self.last_completed=now
                    if not self.capture_excluded and self.last is not None:self.draw(self.last)
                except Exception as exc:
                    self.last=None;self.overlay.withdraw();self.status.set('Cannot capture selected game window: '+friendly_error(exc))
        self.root.after(20,self.tick)
    def draw(self,matrix):
        if self.bound_region is None:return
        region=self.bound_region;w,h=region['width'],region['height']
        if sys.platform=='win32':
            from windows import position_window
            position_window(self.overlay,region['left'],region['top'],w,h)
        else:self.overlay.geometry(f"{w}x{h}{region['left']:+d}{region['top']:+d}")
        self.canvas.delete('all')
        bounds=self.last_bounds or TerrainTracker.viewport(w,h)
        mini=self.is_minimap();shape=self.last_shape if mini else 'rectangle'
        if mini:bounds=(bounds[0]+8,bounds[1]+8,bounds[2]-8,bounds[3]-8)
        nodes=self.active_nodes();coords=project(matrix,[(n['X'],n['Y']) for n in nodes])
        edges=list(zip(range(len(nodes)-1),range(1,len(nodes))))
        if self.loop.get() and len(nodes)>1:edges.append((len(nodes)-1,0))
        for i,j in edges:
            segment=clip_map_segment(coords[i],coords[j],bounds,shape)
            if segment:
                self.canvas.create_line(*segment,fill='#13202c',width=4 if mini else 5)
                self.canvas.create_line(*segment,fill=ROUTE,width=2 if mini else 3,arrow='last',arrowshape=(5,6,2) if mini else (7,9,3))
        left,top,right,bottom=bounds
        placed=[]
        # Label the current stop first, then prevent labels overlapping each other.
        order=([self.next_node] if nodes else [])+[i for i in range(len(nodes)) if i!=self.next_node]
        for i in order:
            node=nodes[i];x,y=coords[i]
            if not inside_map(x,y,bounds,shape,margin=10 if mini else 20):continue
            marker(self.canvas,x,y,node['Kind'],size=4 if mini else 6)
            if i==self.next_node:
                ring=7 if mini else 9;self.canvas.create_oval(x-ring,y-ring,x+ring,y+ring,outline='#f2d65d',width=2 if mini else 3)
            if self.labels.get() and (not mini or i==self.next_node):
                text=f'{i+1}. {label(node)}';text=text if len(text)<=35 else text[:32]+'...'
                item=self.canvas.create_text(x+10,y-11,text=text,anchor='w',fill='#e7edf5',font=('Segoe UI',9,'bold'))
                rect=self.canvas.bbox(item)
                if rect and all(inside_map(xx,yy,bounds,shape,margin=3) for xx in (rect[0],rect[2]) for yy in (rect[1],rect[3])) and not any(rect[0]<b[2]+4 and rect[2]+4>b[0] and rect[1]<b[3]+3 and rect[3]+3>b[1] for b in placed):
                    background=self.canvas.create_rectangle(*rect,fill='#17232e',outline='');self.canvas.tag_lower(background,item);placed.append(rect)
                else:self.canvas.delete(item)
        if not self.demo:
            self.overlay.deiconify();self.overlay.update_idletasks()
            from windows import overlay_styles
            self.capture_excluded=overlay_styles(self.overlay)
    def session(self):
        return {'format':'aion2-visual-route-v4','reference':self.ref_id,'id':self.route_id,'name':self.route_name.get().strip()[:100] or 'Untitled route','nodes':self.nodes,'next':self.next_node,'loop':self.loop.get(),'labels':self.labels.get(),'hide_moving':self.hide_moving.get(),'opacity':self.opacity.get(),'filters':{k:v.get() for k,v in self.filters.items()}}
    def apply_session(self,data):
        data=decode_route(data,self.ref_id,self.reference.size)
        self.nodes=data['nodes'];self.next_node=data['next'];self.route_name.set(data['name'])
        self.loop.set(bool(data.get('loop',True)));self.labels.set(bool(data.get('labels',True)));self.opacity.set(data['opacity']);self.hide_moving.set(bool(data.get('hide_moving',True)))
        for k,v in self.filters.items():v.set(bool(data['filters'].get(k,True)))
        self.route_id=str(data.get('id') or uuid.uuid4())[:100]
    def is_minimap(self):return self.overlay_mode.get()=='Minimap / floating map'
    def hide_for_motion(self):return self.hide_moving.get() and not self.is_minimap()
    def restore_overlay_preferences(self):
        self.overlay_mode.set('Minimap / floating map' if self.profile.get('overlay_mode')=='minimap' else 'Big map')
        config=minimap_settings(self.profile.get('minimap'))
        self.minimap_info.set(('Saved '+('round' if config['shape']=='ellipse' else 'rectangular')+' map area. Re-select if the panel moves.') if config else 'No minimap area selected yet.')
    def change_overlay_mode(self,event=None):
        self.profile['overlay_mode']='minimap' if self.is_minimap() else 'big';self.store.write()
        self.generation+=1;self.motion.reset();self.last=None;self.last_bounds=None;self.overlay.withdraw()
        self.status.set('Set the minimap area first.' if self.is_minimap() and not self.profile.get('minimap') else 'Waiting for matching '+('minimap' if self.is_minimap() else 'big map')+' terrain')
    def choose_minimap_area(self):
        if self.target is None and not self.demo:self.status.set('Bind the game first, then show its minimap / floating map.');return
        self.last=None;self.overlay.withdraw();self.generation+=1
        self.status.set('Show the minimap in the game now - capturing its area in 3 seconds.')
        profile_id=self.profile['id'];self.root.after(3000,lambda:self.finish_minimap_area(profile_id))
    def finish_minimap_area(self,profile_id):
        if self.closing or self.profile['id']!=profile_id:return
        try:
            if self.demo:frame=cv2.imread(str(self.demo))
            else:
                from windows import client_region,foreground
                region=client_region(self.target)
                if region is None or foreground()!=self.target:self.status.set('Area setup cancelled. Keep the bound game focused during the countdown.');return
                self.overlay.withdraw();self.root.update_idletasks()
                frame=self.capture_frame(region)
            if frame is None:raise ValidationError('Cannot capture the map area.')
            dialog=MapAreaDialog(self.root,Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)),self.profile.get('minimap'))
            if dialog.result:
                self.profile['minimap']=minimap_settings(dialog.result);self.overlay_mode.set('Minimap / floating map');self.change_overlay_mode();self.restore_overlay_preferences()
                self.status.set('Minimap area saved. Return to the game for tracking.')
        except Exception as exc:self.status.set('Cannot set minimap area: '+friendly_error(exc))
    def tracker_spec(self):
        config=minimap_settings(self.profile.get('minimap'));mini=self.is_minimap()
        return (str(self.store.image_path(self.profile)),self.profile.get('header')=='altgard' and (ROOT/'assets'/'map-header.png').exists() and not mini,'minimap' if mini else 'big',tuple(config['bounds']) if config else None,config['shape'] if config else 'rectangle')
    def refresh_profiles(self,reset_group=True):
        source=profile_source(self.profile)
        if reset_group:self.profile_group.set('interactive' if source in ('interactive','welcome') else 'picture')
        group=self.profile_group.get()
        self.profile_entries=[p for p in self.store.profiles if profile_source(p)==group]
        self.profile_selector['values']=[p['name'] for p in self.profile_entries]
        if self.profile in self.profile_entries:self.profile_selector.current(self.profile_entries.index(self.profile))
        else:self.profile_selector.set('Choose a saved zone' if self.profile_entries else 'No zones yet — create one below')
        prefix='Interactive map' if source=='interactive' else 'Picture'
        self.active_zone_text.set('Choose an included world or add your own picture.' if source=='welcome' else f"Active {prefix.lower()} zone: {self.profile['name']}")
    def activate_profile(self,profile):
        image=load_image(self.store.image_path(profile))
        if self.editor:self.editor.close()
        self.profile=profile;self.reference=image;self.ref_id=profile['reference'];self.catalog=profile['catalog'];self.saved_routes=profile['routes']
        self.store.data['active']=profile['id'];self.load_session();self.refresh_library();self.refresh_profiles();self.load_model_preferences();self.restore_overlay_preferences();self.store.write()
        self.generation+=1;self.motion.reset();self.last=None;self.overlay.withdraw();self.route_changed(save=False)
        self.detail.set(f"{profile['name']} | {image.width} x {image.height} | {len(self.catalog)} catalog markers")
        self.status.set('Zone changed - waiting for matching map terrain')
    def switch_profile(self,event=None):
        index=self.profile_selector.current()
        if index<0:return
        target=self.profile_entries[index]
        if not self.store_route():return
        self.activate_profile(target)
    def new_profile(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('Map picture','*.png *.jpg *.jpeg *.webp *.bmp')])
        if not path:return
        try:
            image=load_image(path);dialog=CropDialog(self.root,image)
            if not dialog.result:return
            if not self.store_route():return
            name,crop=dialog.result;profile=self.store.create(name,image,crop);self.activate_profile(profile);self.open_editor()
        except (ValueError,TypeError,KeyError,OSError) as exc:messagebox.showerror('New profile',friendly_error(exc),parent=self.root)
    def open_map_browser(self):
        if self.map_browser and self.map_browser.window.winfo_exists():
            self.map_browser.window.deiconify();self.map_browser.window.lift();return
        try:
            from map_ui import MapBrowser
            self.map_browser=MapBrowser(self,marker)
        except (ValueError,TypeError,KeyError,OSError) as exc:messagebox.showerror('Interactive map',friendly_error(exc),parent=self.root)
    def crop_profile(self):
        try:
            dialog=CropDialog(self.root,self.reference)
            if not dialog.result:return
            if not self.store_route():return
            name,crop=dialog.result;old=self.profile;x0,y0,x1,y1=crop
            nodes=[dict(n,X=n['X']-x0,Y=n['Y']-y0) for n in self.catalog if x0<=n['X']<=x1 and y0<=n['Y']<=y1]
            profile=self.store.create(name,self.reference,crop,zone_source=profile_source(old),map_world=old.get('map_world',''),map_name=old.get('map_name',''));profile['catalog']=nodes
            ox,oy=old['crop'][:2];profile['source_size']=old['source_size'];profile['crop']=[ox+x0,oy+y0,ox+x1,oy+y1]
            self.store.write();self.activate_profile(profile);self.open_editor()
        except (ValueError,TypeError,OSError) as exc:messagebox.showerror('Crop zone',friendly_error(exc),parent=self.root)
    def rename_profile(self):
        name=simpledialog.askstring('Rename zone','Zone name:',initialvalue=self.profile['name'],parent=self.root)
        if name is None or not name.strip():return
        previous=self.profile['name'];self.profile['name']=name.strip()[:100]
        try:self.store.write();self.refresh_profiles()
        except (OSError,ValueError) as exc:self.profile['name']=previous;messagebox.showerror('Rename zone',friendly_error(exc),parent=self.root)
    def delete_profile(self):
        if len(self.store.profiles)<2:messagebox.showinfo('Delete zone','Keep at least one zone profile. Create another before deleting this one.',parent=self.root);return
        name=self.profile['name']
        if not messagebox.askyesno('Delete zone?',f'Delete "{name}" and all its saved routes?',parent=self.root):return
        if not messagebox.askyesno('Confirm zone deletion again',f'Final confirmation: delete "{name}" and its routes? Export the profile first if you need a copy.',default='no',parent=self.root):return
        old_profiles=self.store.profiles;old_active=self.store.data['active'];remaining=[p for p in old_profiles if p['id']!=self.profile['id']]
        self.store.data['profiles']=remaining;self.store.data['active']=remaining[0]['id']
        try:self.store.write()
        except (OSError,ValueError) as exc:self.store.data['profiles']=old_profiles;self.store.data['active']=old_active;messagebox.showerror('Delete zone',friendly_error(exc),parent=self.root);return
        self.activate_profile(remaining[0])
    def load_model_preferences(self):
        prefs=self.profile.get('model_preferences',{})
        self.plan_prompt.delete('1.0','end');self.plan_prompt.insert('1.0',str(prefs.get('prompt','Prioritize a short loop. Keep collection order practical.'))[:10000])
        self.plan_source.set('Filtered catalog' if prefs.get('source')=='Filtered catalog' else 'Current route');self.plan_subset.set(bool(prefs.get('subset',False)))
        default_mode='image' if not self.nodes else 'stops'
        self.plan_mode.set('Draw path from image' if prefs.get('mode',default_mode)=='image' else 'Order existing stops')
    def export_profile(self):
        path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.profile.json',initialfile='zone.profile.json',filetypes=[('Profile JSON','*.json')])
        if not path:return
        try:
            if self.store_route():self.store.export(self.profile,path)
        except (ValueError,OSError) as exc:messagebox.showerror('Export profile',friendly_error(exc),parent=self.root)
    def import_profile(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('Profile JSON','*.json')])
        if not path:return
        try:
            if not self.store_route():return
            profile=self.store.import_file(path);self.activate_profile(profile)
        except (ValueError,TypeError,KeyError,OSError) as exc:messagebox.showerror('Import profile',friendly_error(exc),parent=self.root)
    def delete_route(self):
        name=self.route_name.get().strip() or 'Untitled route';victim=self.route_id
        if not messagebox.askyesno('Delete saved route?',f'Delete "{name}" from this profile?',parent=self.root):return
        if not messagebox.askyesno('Confirm deletion again',f'Final confirmation: permanently delete "{name}"? Export it first if you need a copy.',parent=self.root,default='no'):return
        previous=self.profile['routes'];remaining=[r for r in previous if r.get('id')!=victim]
        if not remaining:remaining=[dict(format='aion2-visual-route-v4',reference=self.ref_id,id=str(uuid.uuid4()),name='My route',nodes=[],filters={})]
        previous_current=self.profile['current'];self.profile['routes']=remaining;self.profile['current']=remaining[0]['id']
        try:self.store.write()
        except (OSError,ValueError) as exc:
            self.profile['routes']=previous;self.profile['current']=previous_current;messagebox.showerror('Delete route',friendly_error(exc),parent=self.root);return
        self.saved_routes=remaining;self.apply_session(remaining[0]);self.refresh_library();self.route_changed(save=False)
        if self.editor:self.editor.history=[];self.editor.selected=None;self.editor.draw()
        self.detail.set('Route deleted after both confirmations.')
    def export_model_task(self):
        try:
            resources=[n for n in self.catalog if n['Kind']!='Waypoint' and (n['Kind'] not in self.filters or self.filters[n['Kind']].get())]
            source=self.active_nodes() if self.plan_source.get()=='Current route' else resources
            mode='image' if self.plan_mode.get()=='Draw path from image' or not source else 'stops'
            kinds=[k for k,v in self.filters.items() if v.get()]
            request=context(self.ref_id,self.reference.size,source,self.loop.get(),self.plan_subset.get(),mode,kinds,resources=resources)
            custom=self.plan_prompt.get('1.0','end').strip();prompt=prompt_for(request,custom)
            payload=dict(request,prompt=prompt,profile_name=self.profile['name'],image_file='map.png',resource_legend=resource_legend(request))
            annotated=model_image(self.reference,request)
            path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.model.zip',initialfile='route-model.model.zip',filetypes=[('Model pack','*.zip'),('Legacy task JSON','*.json')])
            if not path:return
            from profiles import atomic_json
            if Path(path).suffix.lower()=='.json':atomic_json(path,dict(payload,image=base64.b64encode(image_bytes(annotated)).decode('ascii')))
            else:
                with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as pack:
                    pack.writestr('map.png',image_bytes(annotated));pack.writestr('legend.png',image_bytes(legend_image(request)));pack.writestr('task.json',json.dumps(payload,indent=2));pack.writestr('PROMPT.txt','Attach map.png and legend.png as IMAGES and task.json as data to a vision-capable model. Then use this prompt:\n\n'+prompt)
            self.plan_mode.set('Draw path from image' if mode=='image' else 'Order existing stops')
            self.profile['planning']=request;self.store_route();self.detail.set(f'Pack exported with {len(resources):,} filtered resources. Attach map.png + task.json; legend.png explains the symbols.')
        except (ValueError,TypeError,OSError) as exc:messagebox.showerror('Export model task',friendly_error(exc),parent=self.root)
    def import_model_plan(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('Model response JSON','*.json')])
        if not path:return
        try:
            request=self.profile.get('planning')
            if not request:raise ValidationError('Export a model task from this profile first.')
            if Path(path).stat().st_size>2_000_000:raise ValidationError('Response file is too large.')
            nodes=accept_response(read_json(path,2_000_000),request)
            image_mode=request.get('mode')=='image'
            if image_mode:
                # Preserve proposed resource metadata for later click-to-add routes.
                catalog=list(self.catalog);keys={(round(n['X'],3),round(n['Y'],3),n['Kind']) for n in catalog}
                for n in nodes:
                    key=(round(n['X'],3),round(n['Y'],3),n['Kind'])
                    if n['Kind']!='Waypoint' and key not in keys:catalog.append(dict(n));keys.add(key)
                if len(catalog)>10000:raise ValidationError('The combined catalog would exceed 10,000 markers.')
            if not self.new_route(nodes,'Model image path' if image_mode else 'Model route'):return
            self.loop.set(request['loop']);self.route_changed()
            if image_mode:
                self.catalog=catalog;self.profile['catalog']=catalog;self.store.write()
                if self.editor:self.editor.draw()
            self.detail.set(f"Model {'image path' if image_mode else 'route'} imported: {len(nodes)} steps. Review estimated positions and travel barriers in the editor.")
        except (ValueError,TypeError,KeyError,OSError) as exc:messagebox.showerror('Import model plan',friendly_error(exc),parent=self.root)
    def refresh_library(self):
        self.route_selector['values']=[f"{r['name']} ({len(r['nodes'])} stops)" for r in self.saved_routes]
        at=next((i for i,r in enumerate(self.saved_routes) if r.get('id')==self.route_id),None)
        if at is not None:self.route_selector.current(at)
        else:self.route_selector.set('Saved routes - choose one')
    def store_route(self):
        try:
            prefs=dict(prompt=self.plan_prompt.get('1.0','end').strip()[:10000],source=self.plan_source.get(),subset=self.plan_subset.get(),mode='image' if self.plan_mode.get()=='Draw path from image' else 'stops')
            record=decode_route(self.session(),self.ref_id,self.reference.size);at=next((i for i,r in enumerate(self.saved_routes) if r.get('id')==self.route_id),None)
            saved=list(self.saved_routes)
            if at is None:saved.append(record)
            else:saved[at]=record
            if len(saved)>500:raise ValidationError('Maximum 500 saved routes per zone.')
            previous=self.profile['routes'];previous_current=self.profile['current'];self.profile['routes']=saved;self.profile['current']=self.route_id
            previous_prefs=self.profile.get('model_preferences');self.profile['model_preferences']=prefs
            try:self.store.write()
            except (OSError,ValueError):
                self.profile['routes']=previous;self.profile['current']=previous_current
                if previous_prefs is None:self.profile.pop('model_preferences',None)
                else:self.profile['model_preferences']=previous_prefs
                raise
            self.saved_routes=saved;self.refresh_library();return True
        except (ValueError,OSError) as exc:self.status.set('Could not save route: '+friendly_error(exc));return False
    def switch_route(self,event=None):
        index=self.route_selector.current()
        if index<0:return
        record=dict(self.saved_routes[index])
        if not self.store_route():return
        self.apply_session(record);self.refresh_library();self.route_changed()
        if self.editor:self.editor.history=[];self.editor.selected=None;self.editor.draw()
    def new_route(self,nodes=None,name='My route'):
        if not self.store_route():return False
        self.route_id=str(uuid.uuid4());self.route_name.set(name);self.nodes=[] if nodes is None else clean_nodes(nodes,self.reference.size);self.next_node=0
        for v in self.filters.values():v.set(True)
        if self.editor:self.editor.close()
        self.route_changed();self.refresh_library();self.open_editor();return True
    def import_catalog(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('Gatherable catalog','*.json *.csv')])
        if not path:return
        try:
            nodes=read_catalog(path,self.ref_id,self.reference.size,self.profile['crop'],self.profile['source_size'])
            previous=self.profile['catalog'];self.profile['catalog']=nodes
            try:self.store.write()
            except (OSError,ValueError):self.profile['catalog']=previous;raise
            self.catalog=nodes;self.detail.set(f'{len(nodes)} catalog markers imported. In Edit route, click a catalog marker to add a stop.')
            if self.editor:self.editor.draw()
        except (ValueError,KeyError,TypeError,OSError) as exc:messagebox.showerror('Import catalog',friendly_error(exc),parent=self.root)
    def load_session(self):
        record=next((r for r in self.saved_routes if r.get('id')==self.profile.get('current')),None)
        if record is None:record=self.saved_routes[0]
        self.apply_session(record)
    def save_session(self):return self.store_route()
    def save_route(self):
        path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.route.json',initialfile='my-route.route.json',filetypes=[('Route JSON','*.json')])
        if path:
            try:atomic_json(path,decode_route(self.session(),self.ref_id,self.reference.size))
            except (OSError,ValueError) as exc:messagebox.showerror('Save route',friendly_error(exc),parent=self.root)
    def load_route(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('Route JSON','*.json')])
        if not path:return
        try:
            if Path(path).stat().st_size>24000000:raise ValidationError('Route file is too large.')
            data=read_json(path)
            if 'MapBase64' in data:
                # Import v1 only if its coordinate reference is the same terrain image.
                original=safe_image(io.BytesIO(base64.b64decode(data['MapBase64'],validate=True)))
                if original.size!=self.reference.size or not np.array_equal(np.asarray(original),np.asarray(self.reference)):raise ValidationError('The v1 route uses a different terrain reference.')
                data={'format':'aion2-visual-route-v2','reference':self.ref_id,'nodes':data['Nodes'],'loop':data.get('Loop',True),'next':0}
            from profiles import reference_aliases
            aliases=reference_aliases(self.reference,self.store.image_path(self.profile).read_bytes())
            aliases.add(self.ref_id)
            imported_reference=data.get('reference',REFERENCE)
            if imported_reference not in aliases:raise ValidationError('This route uses a different map picture.')
            record=decode_route(data,imported_reference,self.reference.size)
            record['reference']=self.ref_id
            if not self.store_route():return
            record['id']=str(uuid.uuid4());self.apply_session(record);self.refresh_library();self.route_changed()
            if self.editor:self.editor.close()
        except (ValueError,KeyError,TypeError,OSError) as exc:messagebox.showerror('Load route',friendly_error(exc),parent=self.root)
    def close(self):
        if self.closing:return
        if not self.save_session():
            messagebox.showerror(NAME,'Changes could not be saved. Free disk space or check permissions, then close again.',parent=self.root);return
        self.closing=True
        self.cancel_calculation.set();self.status.set('Closing safely...')
        if hasattr(self,'capture'):self.capture.close()
        self.overlay.withdraw()
        if self.launcher:self.launcher.window.withdraw()
        self.finish_close()
    def finish_close(self):
        workers=[getattr(self,'worker',None),self.calculation_worker]
        if any(worker is not None and worker.is_alive() for worker in workers):
            self.root.after(30,self.finish_close);return
        for callback in self.root.tk.call('after','info'):
            self.root.after_cancel(callback)
        self.root.destroy()

def main():
    if '--self-test' in sys.argv:
        # Frozen-bundle smoke check uses temporary data and no game capture.
        import tempfile
        with tempfile.TemporaryDirectory(prefix='aetherroute-self-test-') as folder:
            store=ProfileStore(folder,ROOT/'assets')
            image=load_image(store.image_path(store.active))
            assert image.size==(store.active['width'],store.active['height'])
            store.export(store.active,Path(folder)/'roundtrip.json')
            store.import_file(Path(folder)/'roundtrip.json')
            assert len(store.profiles)==2
            from map_data import MapLibrary, catalog
            pack=dict(format='aetherroute-map-v1',name='Self-test',world_id='test',
                      image=base64.b64encode(image_bytes(image)).decode('ascii'),
                      markers=[dict(world=[1,1],Kind='Crystal',Name='Test gem',Id='test-1')],
                      regions=[],world_bounds=[0,0,image.width,image.height],flip_y=False)
            library=MapLibrary(Path(folder)/'map-library');entry=library.add(pack)
            loaded,terrain=library.load(entry);nodes,outside=catalog(loaded,terrain.size)
            assert len(nodes)==1 and nodes[0]['Kind']=='Crystal' and outside==0
            from world_maps import built_in_maps, load_built_in
            worlds=built_in_maps(ROOT)
            assert {entry['world_id'] for entry in worlds}>={'1110','1010'}
            for entry in worlds:
                world,terrain=load_built_in(ROOT,entry)
                nodes,outside=catalog(world,terrain.size)
                assert len(nodes)>0 and outside==0
            preferences=Preferences(folder);preferences.update(developer_mode=True)
            assert Preferences(folder).data['developer_mode'] is True
        return
    demo=None
    if len(sys.argv)>2 and sys.argv[1]=='--demo':demo=Path(sys.argv[2])
    if sys.platform!='win32' and demo is None:raise RuntimeError('Live overlay mode requires Windows 10/11. Use --demo FILE for interface validation.')
    if sys.platform=='win32':
        from windows import dpi_awareness
        dpi_awareness()
    root=tk.Tk();root.withdraw()
    from instance import InstanceLock
    try:lock=InstanceLock(Path(os.environ.get('LOCALAPPDATA',Path.home()))/DATA_FOLDER)
    except OSError:
        messagebox.showinfo(NAME,'AetherRoute is already open, or its data folder cannot be accessed. Close the existing window before starting another.',parent=root);root.destroy();return
    try:
        app=App(root,demo=demo)
        if not demo and app.preferences.data['start_collapsed'] and app.preferences.data['launcher_enabled']:app.hide_main()
        else:app.show_main()
        root.mainloop()
    finally:lock.close()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        if '--self-test' not in sys.argv:
            try:messagebox.showerror(NAME,friendly_error(exc))
            except Exception:pass
        sys.exit(1)
