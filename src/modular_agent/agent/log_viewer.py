"""Read-only floating log window; no screenshot or model requests."""
import ctypes
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter.scrolledtext import ScrolledText


def main():
    path = Path(sys.argv[1])
    window = tk.Tk()
    window.withdraw()
    window.title('Agent 日志（关闭窗口即可隐藏）')
    window.geometry(f'560x360+{max(0, window.winfo_screenwidth() - 580)}+40')
    window.attributes('-topmost', True)
    text = ScrolledText(window, wrap='word', font=('Microsoft YaHei UI', 10),
                        background='#171b22', foreground='#e0e6ed')
    text.pack(fill='both', expand=True)
    text.configure(state='disabled')
    window.update_idletasks()
    user32 = None
    handle = None
    if os.name == 'nt':
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.IsIconic.argtypes = [wintypes.HWND]
        handle = user32.GetParent(window.winfo_id())
        # WS_EX_NOACTIVATE: remain visible above the game without receiving its keys.
        style = user32.GetWindowLongW(handle, -20)
        user32.SetWindowLongW(handle, -20, style | 0x08000000)
    window.deiconify()
    offset = 0

    def refresh():
        nonlocal offset
        try:
            with path.open('r', encoding='utf-8') as stream:
                stream.seek(offset)
                content = stream.read()
                offset = stream.tell()
            if content:
                at_bottom = text.yview()[1] >= .99
                text.configure(state='normal')
                text.insert('end', content)
                # Bound UI memory while retaining the full file on disk.
                lines = int(text.index('end-1c').split('.')[0])
                if lines > 2000:
                    text.delete('1.0', f'{lines - 2000}.0')
                text.configure(state='disabled')
                if at_bottom:
                    text.see('end')
            # Win+D may minimize this window while the launcher searches the desktop.
            if user32 is not None and user32.IsIconic(handle):
                user32.ShowWindow(handle, 4)  # SW_SHOWNOACTIVATE
        except (OSError, UnicodeError):
            pass
        window.after(250, refresh)

    refresh()
    window.mainloop()


if __name__ == '__main__':
    main()
