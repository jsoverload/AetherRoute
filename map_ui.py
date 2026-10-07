"""Pan/zoom resource map inside AetherRoute; packs stay in the user's local account."""
import copy
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
from map_data import MapLibrary, WORLD_NAMES, bounds, catalog, create_profile, from_exports, select_nodes, world_choices, world_to_pixel
from routes import NAMES
from product import NAME
from map_visuals import BG, FG, PANEL, ROUTE
from world_maps import built_in_maps, load_built_in
from security import ValidationError, atomic_json, friendly_error, read_json

class ExportImportDialog(simpledialog.Dialog):
    def __init__(self,parent,choices):
        self.choices=choices;super().__init__(parent,'Choose the world matching your map image')
    def body(self,master):
        ttk.Label(master,text='The image and world must match. Other worlds need their own map image.').pack(pady=8)
        labels=[f'{WORLD_NAMES.get(world,"World "+world)} [{world}] — {count:,} resources' for world,count in self.choices]
        self.world=ttk.Combobox(master,state='readonly',values=labels,width=55);self.world.pack(fill='x')
        ttk.Label(master,text='Map name').pack(anchor='w',pady=(8,0))
        self.name=ttk.Entry(master,width=55);self.name.pack(fill='x')
        self.world.bind('<<ComboboxSelected>>',self.choose_name)
        return self.world
    def choose_name(self,event=None):
        world=self.choices[self.world.current()][0]
        self.name.delete(0,'end');self.name.insert(0,WORLD_NAMES.get(world,'World '+world))
    def validate(self):
        if self.world.current()<0 or not self.name.get().strip():
            messagebox.showinfo('Choose a world','Choose the world matching your image and give the map a name.',parent=self);return False
        return True
    def apply(self):self.result=(self.choices[self.world.current()][0],self.name.get().strip())


class BoundsDialog(simpledialog.Dialog):
    def __init__(self,parent,pack):self.pack=pack;super().__init__(parent,'Map coordinate bounds')
    def body(self,master):
        ttk.Label(master,text='Use the bounds from the map-image configuration. Do not use the smallest\nand largest resource positions: those do not define the image edges.',wraplength=520).grid(row=0,column=0,columnspan=2,pady=8)
        self.fields=[]
        for i,label in enumerate(('Minimum world X','Minimum world Y','Maximum world X','Maximum world Y')):
            ttk.Label(master,text=label).grid(row=i+1,column=0,sticky='w',padx=5,pady=3)
            field=ttk.Entry(master,width=25);field.grid(row=i+1,column=1,padx=5)
            if self.pack.get('world_bounds') is not None:field.insert(0,str(self.pack['world_bounds'][i]))
            self.fields.append(field)
        self.flip=tk.BooleanVar(master,value=self.pack['flip_y'])
        ttk.Checkbutton(master,text='World Y increases toward the top of the image',variable=self.flip).grid(row=5,column=0,columnspan=2,pady=8)
        return self.fields[0]
    def validate(self):
        try:self.values=bounds([float(field.get()) for field in self.fields]);return True
        except (ValueError,OverflowError):messagebox.showerror('Map bounds','Enter four finite bounds from the map configuration.',parent=self);return False
    def apply(self):self.result=(self.values,self.flip.get())


class MapBrowser:
    def __init__(self,app,draw_marker):
        self.app=app;self.draw_marker=draw_marker
        self.library=MapLibrary(app.base_dir/'map-library')
        self.window=tk.Toplevel(app.root);self.window.title(NAME+' — Interactive maps');self.window.configure(bg=BG)
        self.window.attributes('-topmost',app.preferences.data['main_topmost'])
        self.window.geometry('1240x850');self.window.minsize(960,650)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.pack=None;self.image=None;self.entry=None;self.nodes=[];self.filtered=[];self.regions=[]
        self.route=[];self.crop=None;self.scale=1;self.offset=(0,0);self.drag=None;self.redraw=None;self.displayed=[];self.photo=None
        self.pending_fit=True;self.fit_box=None;self.fit_on_resize=True
        self.builtins=built_in_maps(app.resource_root);self.entries=[]
        tools=ttk.Frame(self.window,padding=8);tools.pack(fill='x')
        ttk.Label(tools,text='Choose a world, select resources, then create a zone.',font=('Segoe UI',11,'bold')).pack(side='left')
        ttk.Button(tools,text='Settings',command=app.open_settings).pack(side='right')
        self.devtools=ttk.Frame(self.window,padding=(8,0,8,8))
        for text,command in [('Import map pack',self.import_pack),('Import image + database',self.import_exports),('Export map pack',self.export_pack),('Map bounds',self.configure_bounds),('Import bounds JSON',self.import_bounds)]:
            ttk.Button(self.devtools,text=text,command=command).pack(side='left',padx=3)
        body=ttk.Frame(self.window);body.pack(fill='both',expand=True);self.body=body
        sidebar=ttk.Frame(body,width=275);sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
        self.create_button=ttk.Button(sidebar,text='Create zone + edit route',command=self.create_zone,state='disabled');self.create_button.pack(side='bottom',fill='x',padx=10,pady=10)
        scroll=ttk.Scrollbar(sidebar,orient='vertical');scroll.pack(side='right',fill='y')
        self.sidebar_canvas=tk.Canvas(sidebar,bg=BG,highlightthickness=0,yscrollcommand=scroll.set)
        self.sidebar_canvas.pack(side='left',fill='both',expand=True);scroll.configure(command=self.sidebar_canvas.yview)
        left=ttk.Frame(self.sidebar_canvas,padding=10)
        panel=self.sidebar_canvas.create_window(0,0,anchor='nw',window=left)
        left.bind('<Configure>',lambda e:self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox('all')))
        self.sidebar_canvas.bind('<Configure>',lambda e:self.sidebar_canvas.itemconfigure(panel,width=e.width))
        ttk.Label(left,text='World',font=('Segoe UI',12,'bold')).pack(anchor='w')
        self.selector=ttk.Combobox(left,state='readonly');self.selector.pack(fill='x',pady=5);self.selector.bind('<<ComboboxSelected>>',self.switch_map)
        self.delete_button=ttk.Button(left,text='Delete custom map',command=self.delete_map)
        ttk.Label(left,text='Region').pack(anchor='w');self.region=tk.StringVar(value='All regions')
        self.region_select=ttk.Combobox(left,state='readonly',textvariable=self.region,values=['All regions']);self.region_select.pack(fill='x',pady=5);self.region_select.bind('<<ComboboxSelected>>',self.choose_region)
        ttk.Label(left,text='Search resource name').pack(anchor='w');self.search=tk.StringVar()
        field=ttk.Entry(left,textvariable=self.search);field.pack(fill='x',pady=5);field.bind('<KeyRelease>',lambda e:self.filter_changed())
        ttk.Label(left,text='Resource types',font=('Segoe UI',11,'bold')).pack(anchor='w',pady=(6,3))
        self.types={kind:tk.BooleanVar(value=kind in ('Crystal','Plant')) for kind in NAMES if kind not in ('Custom','Waypoint')}
        for kind,value in self.types.items():ttk.Checkbutton(left,text=NAMES[kind],variable=value,command=self.filter_changed).pack(anchor='w')
        row=ttk.Frame(left);row.pack(fill='x',pady=4)
        ttk.Button(row,text='All',command=lambda:self.set_types(True)).pack(side='left',expand=True,fill='x')
        ttk.Button(row,text='None',command=lambda:self.set_types(False)).pack(side='left',expand=True,fill='x')
        self.count=tk.StringVar(value='Choose an included world.');ttk.Label(left,textvariable=self.count,wraplength=230).pack(anchor='w',pady=8)
        self.mode=tk.StringVar(value='route')
        ttk.Radiobutton(left,text='Pan / click route stops',variable=self.mode,value='route').pack(anchor='w')
        ttk.Radiobutton(left,text='Drag to select an area',variable=self.mode,value='crop').pack(anchor='w')
        ttk.Button(left,text='Fit map / reset area',command=self.reset_area).pack(fill='x',pady=(8,3))
        ttk.Button(left,text='Add resources in area',command=self.add_area).pack(fill='x',pady=3)
        ttk.Button(left,text='Undo last stop',command=self.undo).pack(fill='x',pady=3)
        ttk.Button(left,text='Clear preview route',command=self.clear_route).pack(fill='x',pady=3)
        ttk.Label(left,text='Mouse wheel: zoom\nDrag: pan or select area\nClick resource: add typed stop\nRight-click stop: remove\n\nPreview stops save when you create a zone. The overlay uses the clean terrain image.',wraplength=230,foreground='#b7c5d8').pack(anchor='w')
        self.canvas=tk.Canvas(body,bg=BG,highlightthickness=0);self.canvas.pack(side='left',fill='both',expand=True)
        self.canvas.bind('<Configure>',self.canvas_configured)
        self.canvas.bind('<Map>',lambda e:self.fit(self.fit_box) if self.pending_fit else None)
        self.canvas.bind('<Button-1>',self.press);self.canvas.bind('<B1-Motion>',self.move);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Button-3>',self.remove_stop);self.canvas.bind('<Motion>',self.hover)
        self.canvas.bind('<MouseWheel>',self.zoom);self.canvas.bind('<Button-4>',lambda e:self.zoom(e,1));self.canvas.bind('<Button-5>',lambda e:self.zoom(e,-1))
        self.status=tk.StringVar(value='Included worlds are ready to use. Choose resources and an area to create a zone.')
        ttk.Label(self.window,textvariable=self.status,wraplength=1180,padding=8).pack(fill='x')
        self.refresh_maps();self.refresh_developer_mode()
        preferred=app.profile.get('map_world')
        last=app.preferences.data['last_map']
        entry=next((e for e in self.entries if e['world_id']==preferred and e['name']==app.profile.get('map_name')),None) or next((e for e in self.entries if e['world_id']==preferred),None) or next((e for e in self.entries if e['id']==last),None)
        if entry or self.entries:self.load_entry(entry or self.entries[0])

    def error(self,title,exc):messagebox.showerror(title,friendly_error(exc),parent=self.window)
    def refresh_maps(self):
        self.entries=self.builtins+self.library.entries
        self.selector['values']=[entry['name']+(' (custom)' if not entry.get('builtin') else '') for entry in self.entries]
        if self.entry and self.entry in self.entries:self.selector.current(self.entries.index(self.entry))
    def refresh_developer_mode(self):
        if self.app.developer_mode.get():
            self.devtools.pack(before=self.body,fill='x')
            self.delete_button.pack(fill='x',pady=(0,8),after=self.selector)
        else:self.devtools.pack_forget();self.delete_button.pack_forget()
    def canvas_configured(self,event):
        if self.image and (self.pending_fit or self.fit_on_resize):self.fit(self.fit_box)
        else:self.schedule_draw()
    def allow_replace(self):
        return not self.route or messagebox.askyesno('Unsaved preview route','Switch maps and discard these preview stops? Create a zone first to save them.',default='no',parent=self.window)
    def load_entry(self,entry):
        pack,image=load_built_in(self.app.resource_root,entry) if entry.get('builtin') else self.library.load(entry)
        self.entry=entry;self.pack=pack;self.image=image;self.route=[];self.region.set('All regions');self.search.set('')
        self.region_select['values']=['All regions']+[r['name'] for r in pack['regions']]
        self.crop=(0,0,image.width,image.height);self.pending_fit=True;self.fit_on_resize=True;self.fit_box=None
        self.rebuild();self.fit();self.refresh_maps()
        try:self.app.preferences.update(last_map=entry['id'])
        except (ValueError,OSError):pass  # Remembering the picker is optional.
    def switch_map(self,event=None):
        index=self.selector.current()
        if index<0:return
        if not self.allow_replace():self.refresh_maps();return
        try:self.load_entry(self.entries[index])
        except (ValueError,KeyError,TypeError,OSError) as exc:self.error('Open map',exc)
    def import_pack(self):
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('AetherRoute map pack','*.map.json *.json')])
        if not path or not self.allow_replace():return
        try:entry=self.library.add(read_json(path,50_000_000));self.load_entry(entry)
        except (ValueError,KeyError,TypeError,OSError) as exc:self.error('Import map pack',exc)
    def import_exports(self):
        if not self.allow_replace():return
        image=filedialog.askopenfilename(parent=self.window,title='Choose the clean map image',filetypes=[('Map image','*.webp *.png *.jpg *.jpeg *.bmp')])
        if not image:return
        markers=filedialog.askopenfilename(parent=self.window,title='Choose getMarkers JSON',filetypes=[('Database JSON','*.json'),('All files','*')])
        if not markers:return
        regions=filedialog.askopenfilename(parent=self.window,title='Choose getRegions JSON (Cancel to skip)',filetypes=[('Database JSON','*.json'),('All files','*')])
        try:
            choices=world_choices(markers)
            if not choices:raise ValidationError('No resource worlds were found in this database.')
            dialog=ExportImportDialog(self.window,choices)
            if not dialog.result:return
            world,name=dialog.result
            self.window.configure(cursor='watch');self.window.update_idletasks()
            pack=from_exports(image,markers,regions or None,world,name)
            self.load_entry(self.library.add(pack))
        except (ValueError,KeyError,TypeError,OSError) as exc:self.error('Import database',exc)
        finally:self.window.configure(cursor='')
    def export_pack(self):
        if not self.pack:return
        path=filedialog.asksaveasfilename(parent=self.window,initialfile='world.map.json',defaultextension='.map.json',filetypes=[('Map pack','*.map.json')])
        if path:
            try:atomic_json(path,self.pack,limit=50_000_000)
            except (ValueError,OSError) as exc:self.error('Export map pack',exc)
    def configure_bounds(self):
        if not self.pack:return
        dialog=BoundsDialog(self.window,self.pack)
        if dialog.result:self.apply_bounds(*dialog.result)
    def import_bounds(self):
        if not self.pack:return
        path=filedialog.askopenfilename(parent=self.window,title='Choose map bounds JSON',filetypes=[('Map bounds','*.json')])
        if not path:return
        try:
            data=read_json(path,100_000)
            if not isinstance(data,dict) or data.get('world_id')!=self.pack['world_id']:raise ValidationError('Map bounds must specify this world_id.')
            if type(data.get('flip_y'))!=bool:raise ValidationError('Map bounds must specify true or false for flip_y.')
            boundary=bounds(data.get('world_bounds'))
            if boundary is None:raise ValidationError('This file has no map bounds.')
            self.apply_bounds(boundary,data['flip_y'])
        except (ValueError,KeyError,TypeError,OSError) as exc:self.error('Import bounds',exc)
    def apply_bounds(self,boundary,flip):
        if not self.allow_replace():return
        try:
            if self.entry.get('builtin'):raise ValidationError('Included world bounds are already configured. Import a custom map copy in Developer mode to change them.')
            updated=copy.deepcopy(self.pack);updated['world_bounds']=bounds(boundary);updated['flip_y']=flip
            self.library.update(self.entry,updated);self.pack=updated;self.route=[];self.rebuild();self.fit()
        except (ValueError,KeyError,TypeError,OSError) as exc:self.error('Save bounds',exc)
    def rebuild(self):
        self.nodes=[];self.regions=[];outside=0
        if self.pack['world_bounds'] is not None:
            self.nodes,outside=catalog(self.pack,self.image.size)
            self.regions=[[[world_to_pixel(p,self.pack['world_bounds'],self.image.size,self.pack['flip_y']) for p in poly] for poly in region['polygons']] for region in self.pack['regions']]
            self.status.set(f'{len(self.nodes):,} typed resources placed. {outside:,} positions outside the image. Check landmarks before using the overlay.')
        else:
            self.status.set(f'{len(self.pack["markers"]):,} resources imported, but image-coordinate bounds are missing. Import the map bounds or configure them before resources can be placed.')
        self.create_button.configure(state='normal' if self.pack['world_bounds'] is not None else 'disabled')
        self.filter_changed()
    def set_types(self,value):
        for variable in self.types.values():variable.set(value)
        self.filter_changed()
    def filter_changed(self):
        if not self.pack:return
        index=self.region_select.current()-1
        polygon=self.regions[index] if 0<=index<len(self.regions) else None
        self.filtered=select_nodes(self.nodes,{k for k,v in self.types.items() if v.get()},self.search.get(),polygon)
        self.count.set(f'{len(self.filtered):,} matching resources\n{len(self.area_nodes()):,} in selected area\n{len(self.route)} preview stops')
        self.schedule_draw()
    def choose_region(self,event=None):
        if not self.pack:return
        index=self.region_select.current()-1
        if 0<=index<len(self.regions):
            points=[p for polygon in self.regions[index] for p in polygon]
            if points:
                x0=max(0,math.floor(min(p[0] for p in points)));y0=max(0,math.floor(min(p[1] for p in points)))
                x1=min(self.image.width,math.ceil(max(p[0] for p in points)));y1=min(self.image.height,math.ceil(max(p[1] for p in points)))
                if x1-x0>=80 and y1-y0>=80:self.crop=(x0,y0,x1,y1);self.fit(self.crop)
        else:self.crop=(0,0,self.image.width,self.image.height);self.fit()
        self.filter_changed()
    def reset_area(self):
        if not self.image:return
        self.crop=(0,0,self.image.width,self.image.height);self.region.set('All regions');self.filter_changed();self.fit()
    def fit(self,box=None):
        if not self.image:return
        self.fit_box=box;self.fit_on_resize=True
        x0,y0,x1,y1=box or (0,0,self.image.width,self.image.height)
        w=self.canvas.winfo_width();h=self.canvas.winfo_height()
        if w<=32 or h<=32:self.pending_fit=True;return
        self.pending_fit=False
        self.scale=min((w-30)/(x1-x0),(h-30)/(y1-y0));self.offset=(w/2-(x0+x1)*self.scale/2,h/2-(y0+y1)*self.scale/2);self.schedule_draw()
    def screen(self,x,y):return x*self.scale+self.offset[0],y*self.scale+self.offset[1]
    def image_point(self,x,y):return (x-self.offset[0])/self.scale,(y-self.offset[1])/self.scale
    def zoom(self,event,direction=None):
        if not self.image:return
        self.fit_on_resize=False
        direction=direction if direction is not None else (1 if event.delta>0 else -1)
        x,y=self.image_point(event.x,event.y);self.scale=max(.03,min(12,self.scale*(1.2 if direction>0 else 1/1.2)))
        self.offset=(event.x-x*self.scale,event.y-y*self.scale);self.schedule_draw()
    def press(self,event):
        if self.image:self.fit_on_resize=False;self.drag=(event.x,event.y,self.offset,self.image_point(event.x,event.y))
    def move(self,event):
        if not self.drag:return
        x,y,offset,start=self.drag
        if self.mode.get()=='crop':
            self.canvas.delete('drag-area')
            a,b=self.screen(*start);self.canvas.create_rectangle(a,b,event.x,event.y,outline='#f2d65d',width=2,tags='drag-area')
        else:self.offset=(offset[0]+event.x-x,offset[1]+event.y-y);self.schedule_draw()
    def release(self,event):
        if not self.drag:return
        x,y,offset,start=self.drag;self.drag=None
        if self.mode.get()=='crop':
            end=self.image_point(event.x,event.y)
            x0=max(0,math.floor(min(start[0],end[0])));y0=max(0,math.floor(min(start[1],end[1])))
            x1=min(self.image.width,math.ceil(max(start[0],end[0])));y1=min(self.image.height,math.ceil(max(start[1],end[1])))
            if x1-x0<80 or y1-y0<80:self.status.set('Select an area at least 80 × 80 image pixels.');self.schedule_draw();return
            self.crop=(x0,y0,x1,y1);self.filter_changed()
        elif math.hypot(event.x-x,event.y-y)<4:
            node=self.nearest(event.x,event.y)
            if node and not any(n['Id']==node['Id'] for n in self.route):
                if len(self.route)>=1000:self.status.set('Maximum 1000 route stops.');return
                self.route.append(dict(node));self.filter_changed()
    def nearest(self,x,y):
        candidates=[(math.hypot(px-x,py-y),node) for px,py,node in self.displayed]
        if not candidates:return None
        distance,node=min(candidates,key=lambda item:item[0])
        return node if distance<=11 else None
    def hover(self,event):
        self.canvas.delete('hover')
        node=self.nearest(event.x,event.y)
        if node:
            text=f'{node.get("Name") or NAMES[node["Kind"]]} · {NAMES[node["Kind"]]}'
            item=self.canvas.create_text(event.x+14,event.y-18,text=text,anchor='sw',fill=FG,font=('Segoe UI',10),tags='hover')
            box=self.canvas.bbox(item)
            background=self.canvas.create_rectangle(*box,fill=BG,outline=FG,tags='hover');self.canvas.tag_lower(background,item)
    def remove_stop(self,event):
        node=self.nearest(event.x,event.y)
        if node:self.route=[n for n in self.route if n['Id']!=node['Id']];self.filter_changed()
    def area_nodes(self):
        if not self.crop:return []
        x0,y0,x1,y1=self.crop
        return [n for n in self.filtered if x0<=n['X']<=x1 and y0<=n['Y']<=y1]
    def add_area(self):
        if not self.pack or self.pack['world_bounds'] is None:return
        combined={n['Id']:n for n in self.route}
        for node in self.area_nodes():combined.setdefault(node['Id'],dict(node))
        if len(combined)>1000:messagebox.showinfo('Too many stops','Select a smaller area or fewer resource types. A route supports at most 1000 stops.',parent=self.window);return
        self.route=list(combined.values());self.filter_changed()
    def undo(self):
        if self.route:self.route.pop();self.filter_changed()
    def clear_route(self):self.route=[];self.filter_changed()
    def schedule_draw(self):
        if self.redraw is None:self.redraw=self.window.after(35,self.draw)
    def draw(self):
        self.redraw=None;self.canvas.delete('all');self.displayed=[]
        if not self.image:
            self.canvas.create_text(30,30,anchor='nw',text='No worlds are available. Extract the complete AetherRoute package.\nCustom worlds can be added in Settings → Developer mode.',fill=FG,font=('Segoe UI',15));return
        if self.pending_fit:
            self.fit(self.fit_box)
            if self.pending_fit:return
        w=max(1,self.canvas.winfo_width());h=max(1,self.canvas.winfo_height())
        left,top=self.image_point(0,0);right,bottom=self.image_point(w,h)
        x0=max(0,math.floor(left));y0=max(0,math.floor(top));x1=min(self.image.width,math.ceil(right));y1=min(self.image.height,math.ceil(bottom))
        if x1>x0 and y1>y0:
            raster=self.image.crop((x0,y0,x1,y1)).resize((max(1,round((x1-x0)*self.scale)),max(1,round((y1-y0)*self.scale))),Image.Resampling.BILINEAR)
            self.photo=ImageTk.PhotoImage(raster,master=self.window);self.canvas.create_image(*self.screen(x0,y0),anchor='nw',image=self.photo)
        index=self.region_select.current()-1
        if 0<=index<len(self.regions):
            for polygon in self.regions[index]:self.canvas.create_line(*[v for p in polygon+[polygon[0]] for v in self.screen(*p)],fill='#f2d65d',width=2)
        for node in self.filtered:
            x,y=self.screen(node['X'],node['Y'])
            if -12<=x<=w+12 and -12<=y<=h+12:self.draw_marker(self.canvas,x,y,node['Kind'],size=5);self.displayed.append((x,y,node))
        for a,b in zip(self.route,self.route[1:]):self.canvas.create_line(*self.screen(a['X'],a['Y']),*self.screen(b['X'],b['Y']),fill=ROUTE,width=3)
        for i,node in enumerate(self.route):
            x,y=self.screen(node['X'],node['Y']);self.canvas.create_oval(x-9,y-9,x+9,y+9,outline='#f5fbff',width=2)
            self.canvas.create_text(x+10,y-12,text=str(i+1),fill='#141b28',font=('Segoe UI',10,'bold'))
            if not any(n['Id']==node['Id'] for _,_,n in self.displayed):self.displayed.append((x,y,node))
        if self.crop:
            x0,y0,x1,y1=self.crop;self.canvas.create_rectangle(*self.screen(x0,y0),*self.screen(x1,y1),outline='#f2d65d',width=2,dash=(6,4))
    def create_zone(self):
        if not self.pack or self.pack['world_bounds'] is None:return
        name=simpledialog.askstring('Create zone','Zone profile name:',initialvalue=(self.pack['name']+' — '+self.region.get())[:100],parent=self.window)
        if not name:return
        try:
            if not self.app.store_route():return
            profile=create_profile(self.app.store,self.pack,self.image,self.crop,self.filtered,self.route,name)
            self.app.activate_profile(profile);self.app.open_editor();self.route=[];self.filter_changed()
            self.status.set(f'Created {name}. The database catalog keeps exact resource types. Use Calculate shortest or Model planning for route ordering.')
        except (ValueError,KeyError,TypeError,OSError) as exc:self.error('Create zone',exc)
    def delete_map(self):
        if not self.entry:return
        if self.entry.get('builtin'):
            messagebox.showinfo('Included world','Included worlds are part of AetherRoute. Only custom map entries can be deleted.',parent=self.window);return
        if not messagebox.askyesno('Delete saved map?','Remove this map from the map browser? Created profiles stay saved.',parent=self.window):return
        if not messagebox.askyesno('Confirm map deletion again','Final confirmation: remove this map and its preview route from the browser?',default='no',parent=self.window):return
        try:
            self.library.delete(self.entry);self.entry=None;self.pack=None;self.image=None;self.route=[];self.nodes=[];self.filtered=[];self.regions=[];self.selector.set('');self.refresh_maps();self.create_button.configure(state='disabled')
            if self.entries:self.load_entry(self.entries[0])
            else:self.count.set('No maps available.');self.status.set('Custom map removed. Zone profiles were preserved.');self.schedule_draw()
        except (ValueError,KeyError,TypeError,OSError) as exc:self.error('Delete map',exc)
    def close(self):
        if self.route and not messagebox.askyesno('Unsaved preview route','Close without saving these preview stops? Create a zone to keep them.',default='no',parent=self.window):return
        if self.redraw is not None:self.window.after_cancel(self.redraw)
        self.app.map_browser=None;self.window.destroy()
