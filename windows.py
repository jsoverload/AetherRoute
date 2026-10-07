"""Window metadata and non-consuming key observation. No game memory or injection."""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetWindowTextW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
user32.GetWindowLongW.argtypes = [wintypes.HWND,ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.SetWindowLongW.argtypes = [wintypes.HWND,ctypes.c_int,wintypes.LONG]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND,wintypes.DWORD]
user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD]
user32.MonitorFromWindow.restype=wintypes.HANDLE
user32.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.c_void_p]
user32.SetForegroundWindow.argtypes=[wintypes.HWND]
user32.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
user32.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]


def dpi_awareness():
    try:
        user32.SetProcessDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError,OSError):
        try:ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError,OSError):pass


def foreground():return user32.GetForegroundWindow()

def window_exists(hwnd):return bool(user32.IsWindow(hwnd))

def title(hwnd):
    text=ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd,text,len(text))
    return text.value

def client_region(hwnd):
    if not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):return None
    rect=wintypes.RECT();point=wintypes.POINT(0,0)
    if not user32.GetClientRect(hwnd,ctypes.byref(rect)) or not user32.ClientToScreen(hwnd,ctypes.byref(point)):return None
    width,height=rect.right-rect.left,rect.bottom-rect.top
    if width<640 or height<360:return None
    return dict(left=point.x,top=point.y,width=width,height=height)

def root_handle(widget):return user32.GetAncestor(widget.winfo_id(),2)

def overlay_styles(widget):
    hwnd=root_handle(widget)
    # Layered + transparent + tool window + no activation: input reaches the game.
    style=user32.GetWindowLongW(hwnd,-20)
    user32.SetWindowLongW(hwnd,-20,style|0x00080000|0x20|0x80|0x08000000)
    # Keep our own route out of terrain captures when the Windows compositor supports it.
    return bool(user32.SetWindowDisplayAffinity(hwnd,0x11))

def key_down(vk):return bool(user32.GetAsyncKeyState(vk)&0x8000)

def launcher_styles(widget):
    hwnd=root_handle(widget);style=user32.GetWindowLongW(hwnd,-20)
    # Clickable tool window: deliberately omit WS_EX_TRANSPARENT.
    user32.SetWindowLongW(hwnd,-20,style|0x80|0x08000000)
    user32.SetWindowPos(hwnd,wintypes.HWND(-1),0,0,0,0,0x1|0x2|0x10|0x20)
    return bool(user32.SetWindowDisplayAffinity(hwnd,0x11))

def show_without_activation(widget):
    hwnd=root_handle(widget);user32.ShowWindow(hwnd,4)
    user32.SetWindowPos(hwnd,wintypes.HWND(-1),0,0,0,0,0x1|0x2|0x10)

def position_window(widget,x,y,width,height):
    # Native coordinates can be negative on monitors left of the primary.
    # Tk's negative geometry offsets instead mean distance from a screen edge.
    widget.update_idletasks()
    user32.SetWindowPos(root_handle(widget),wintypes.HWND(-1),int(x),int(y),int(width),int(height),0x10)

def activate_window(hwnd):
    if user32.IsWindow(hwnd):user32.SetForegroundWindow(hwnd)

def monitor_work_area(hwnd):
    class MonitorInfo(ctypes.Structure):
        _fields_=[('cbSize',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),('flags',wintypes.DWORD)]
    monitor=user32.MonitorFromWindow(hwnd,2);info=MonitorInfo();info.cbSize=ctypes.sizeof(info)
    if not user32.GetMonitorInfoW(monitor,ctypes.byref(info)):raise OSError('Display work area is unavailable.')
    r=info.work;return r.left,r.top,r.right-r.left,r.bottom-r.top
