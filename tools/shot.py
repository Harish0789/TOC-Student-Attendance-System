"""Screenshot helper (Windows): grab a Tk window exactly as it appears on screen."""

import ctypes
import ctypes.wintypes as wt

from PIL import ImageGrab


def window_rect(root):
    hwnd = int(root.wm_frame(), 16)
    rect = wt.RECT()
    # DWMWA_EXTENDED_FRAME_BOUNDS = 9 gives the visible frame without the drop shadow
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect),
                                                  ctypes.sizeof(rect)) != 0:
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def capture(root, path, widget=None):
    """Save a PNG of the whole window (or just `widget`)."""
    root.lift()
    root.attributes("-topmost", True)
    root.update_idletasks()
    root.update()
    if widget is None:
        box = window_rect(root)
    else:
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        box = (x, y, x + widget.winfo_width(), y + widget.winfo_height())
    ImageGrab.grab(bbox=box, all_screens=True).save(path)
    return path
