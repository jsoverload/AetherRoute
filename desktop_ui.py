"""Clickable game launcher and local preferences; no game input interception."""
import math
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
from map_visuals import BG, FG, PANEL, ROUTE
from product import NAME, VERSION, SUPPORT_URL
from security import friendly_error

def open_support_page(parent):
    try:
        if not webbrowser.open(SUPPORT_URL,new=2):
            messagebox.showinfo('Support '+NAME,'Open this address in your browser:\n'+SUPPORT_URL,parent=parent)
    except (OSError,webbrowser.Error) as exc:messagebox.showerror('Open support page',friendly_error(exc),parent=parent)

class SettingsDialog:
    def __init__(self,app):
        self.app=app;self.window=tk.Toplevel(app.root);self.window.title(NAME+' — Settings');self.window.configure(bg=BG)
        self.window.transient(app.root);self.window.resizable(False,False)
        body=ttk.Frame(self.window,padding=18);body.pack(fill='both',expand=True)
        ttk.Label(body,text=NAME+' '+VERSION,font=('Segoe UI',16,'bold')).pack(anchor='w',pady=(0,12))
        self.values={key:tk.BooleanVar(value=app.preferences.data[key]) for key in ('launcher_enabled','start_collapsed','main_topmost','developer_mode')}
        labels={'launcher_enabled':'Show the small game launcher','start_collapsed':'Start with the main window hidden','main_topmost':'Keep the main window above the game','developer_mode':'Developer mode: custom worlds and icon tools'}
        for key,value in self.values.items():ttk.Checkbutton(body,text=labels[key],variable=value).pack(anchor='w',pady=4)
        ttk.Label(body,text='Normal use: choose an included world or create a picture zone.\nDeveloper mode adds database imports, coordinate bounds, custom\ncatalogs and icon teaching. Your saved zones remain available.',wraplength=460,foreground='#b7c5d8').pack(anchor='w',pady=12)
        ttk.Separator(body).pack(fill='x',pady=8)
        ttk.Label(body,text='Free and open source. Optional support helps development.').pack(anchor='w')
        ttk.Button(body,text='Buy me a coffee on Ko-fi ↗',style='Coffee.TButton',command=lambda:open_support_page(self.window)).pack(fill='x',pady=8)
        row=ttk.Frame(body);row.pack(fill='x',pady=(8,0))
        ttk.Button(row,text='Save settings',command=self.save).pack(side='left',expand=True,fill='x',padx=3)
        ttk.Button(row,text='Cancel',command=self.window.destroy).pack(side='left',expand=True,fill='x',padx=3)
    def save(self):
        try:
            self.app.apply_preferences(**{key:value.get() for key,value in self.values.items()})
            self.window.destroy()
        except (ValueError,OSError) as exc:messagebox.showerror('Save settings',friendly_error(exc),parent=self.window)

def launcher_position(bounds,size,margin):
    left,top,width,height=bounds;w,h=size
    return (max(left,left+width-w-margin[0]),max(top,top+height-h-margin[1]))

class GameLauncher:
    def __init__(self,app):
        self.app=app;self.window=tk.Toplevel(app.root);self.window.withdraw();self.window.overrideredirect(True)
        self.window.configure(bg=BG);self.window.attributes('-topmost',True)
        self.width=178;self.height=48;self.region=None;self.drag_start=None;self.moved=False;self.callback=None
        self.canvas=tk.Canvas(self.window,width=self.width,height=self.height,bg=BG,highlightthickness=0,cursor='hand2');self.canvas.pack()
        self.canvas.create_rectangle(1,1,self.width-2,self.height-2,fill=BG,outline='#365f79',width=2)
        self.canvas.create_oval(9,9,39,39,fill=PANEL,outline=ROUTE,width=2)
        self.canvas.create_text(24,24,text='AR',fill=ROUTE,font=('Segoe UI',9,'bold'))
        self.canvas.create_text(50,16,text=NAME,anchor='w',fill=FG,font=('Segoe UI',10,'bold'))
        self.canvas.create_text(50,33,text='Open routes  ›',anchor='w',fill='#b7c5d8',font=('Segoe UI',8))
        self.canvas.bind('<Button-1>',self.press);self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Button-3>',self.context_menu)
        self.window.update_idletasks();self.capture_excluded=False
        if sys.platform=='win32':
            from windows import launcher_styles
            self.capture_excluded=launcher_styles(self.window)
        self.sync();self.callback=app.root.after(300,self.tick)
    def bounds(self):
        if self.app.target and not self.app.demo and sys.platform=='win32':
            from windows import client_region, foreground, window_exists
            if not window_exists(self.app.target):
                self.app.target=None;self.app.status.set('Game closed. Open Aion 2 and bind it again to resume tracking.')
            else:
                if foreground()!=self.app.target:return None
                region=client_region(self.app.target)
                if not region:return None
                return region['left'],region['top'],region['width'],region['height']
        if sys.platform=='win32':
            from windows import monitor_work_area, root_handle
            return monitor_work_area(root_handle(self.app.root))
        return (0,0,self.app.root.winfo_screenwidth(),self.app.root.winfo_screenheight())
    def position(self,x,y):
        if sys.platform=='win32':
            from windows import position_window
            position_window(self.window,x,y,self.width,self.height)
        else:self.window.geometry(f'{self.width}x{self.height}{x:+d}{y:+d}')
    def sync(self):
        if self.app.closing or not self.app.preferences.data['launcher_enabled'] or self.app.root.state()!='withdrawn':self.window.withdraw();return
        bounds=self.bounds()
        if bounds is None:self.window.withdraw();return
        self.region=bounds
        if not self.drag_start:
            x,y=launcher_position(bounds,(self.width,self.height),self.app.preferences.data['launcher_margin'])
            self.position(x,y)
        if self.window.state()=='withdrawn':
            if sys.platform=='win32':
                # Map the badge without stealing foreground focus from the game.
                from windows import show_without_activation
                self.window.deiconify();show_without_activation(self.window)
            else:self.window.deiconify()
    def tick(self):
        self.callback=None
        if self.app.closing:return
        self.sync();self.callback=self.app.root.after(300,self.tick)
    def press(self,event):
        self.drag_start=(event.x_root,event.y_root,self.window.winfo_x(),self.window.winfo_y());self.moved=False
    def drag(self,event):
        if not self.drag_start or not self.region:return
        sx,sy,x,y=self.drag_start;dx,dy=event.x_root-sx,event.y_root-sy
        if math.hypot(dx,dy)>5:self.moved=True
        if not self.moved:return
        left,top,width,height=self.region
        x=max(left,min(left+width-self.width,x+dx));y=max(top,min(top+height-self.height,y+dy))
        self.position(x,y)
    def release(self,event):
        if not self.drag_start:return
        self.drag_start=None
        if not self.moved:self.app.show_main();return
        if self.region:
            left,top,width,height=self.region
            margin=[max(0,left+width-self.width-self.window.winfo_x()),max(0,top+height-self.height-self.window.winfo_y())]
            try:self.app.preferences.update(launcher_margin=margin)
            except (ValueError,OSError) as exc:messagebox.showerror('Launcher position',friendly_error(exc),parent=self.window)
    def reset_position(self):
        try:self.app.preferences.update(launcher_margin=[18,36]);self.sync()
        except (ValueError,OSError) as exc:messagebox.showerror('Launcher position',friendly_error(exc),parent=self.window)
    def context_menu(self,event):
        menu=tk.Menu(self.window,tearoff=False,bg=PANEL,fg=FG)
        menu.add_command(label='Open '+NAME,command=self.app.show_main)
        menu.add_command(label='Reset to bottom-right',command=self.reset_position)
        menu.add_command(label='Settings',command=lambda:(self.app.show_main(),self.app.open_settings()))
        menu.add_separator();menu.add_command(label='Quit '+NAME,command=self.app.close)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
