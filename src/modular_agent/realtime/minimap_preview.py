"""Native-pixel map viewport. Resizing the window never stretches the map."""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import cv2


class MapPreview:
    def __init__(self,title,image,*,visible=True):
        self.root = tk.Tk();self.root.title(title+' — 100%')
        if not visible:self.root.withdraw()
        self.closed = False
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.root.bind('<Escape>',lambda event:self.close())
        self.root.bind('q',lambda event:self.close())
        self.root.rowconfigure(0,weight=1);self.root.columnconfigure(0,weight=1)
        self.canvas = tk.Canvas(self.root,background='#202020',highlightthickness=0)
        horizontal = ttk.Scrollbar(self.root,orient='horizontal',command=self.canvas.xview)
        vertical = ttk.Scrollbar(self.root,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=horizontal.set,yscrollcommand=vertical.set)
        self.canvas.grid(row=0,column=0,sticky='nsew')
        vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        self.item = self.canvas.create_image(0,0,anchor='nw')
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-1 if e.delta>0 else 1,'units'))
        self.canvas.bind('<Shift-MouseWheel>',lambda e:self.canvas.xview_scroll(-1 if e.delta>0 else 1,'units'))
        h,w = image.shape[:2]
        width = min(w+22,int(self.root.winfo_screenwidth()*.8))
        height = min(h+30,int(self.root.winfo_screenheight()*.8))
        self.root.geometry(f'{width}x{height}')
        self.show(image)

    def show(self,image):
        if self.closed:return False
        try:
            rgb = Image.fromarray(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
            self.photo = ImageTk.PhotoImage(rgb,master=self.root)
            self.canvas.itemconfigure(self.item,image=self.photo)
            self.canvas.configure(scrollregion=(0,0,image.shape[1],image.shape[0]))
            self.root.update_idletasks();self.root.update()
        except tk.TclError:
            self.closed = True
        return not self.closed

    def close(self):
        if not self.closed:
            self.closed = True
            self.root.destroy()
