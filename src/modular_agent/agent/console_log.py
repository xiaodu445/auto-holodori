"""Persistent console output and an optional independent desktop viewer."""
from datetime import datetime
from pathlib import Path
import os
import subprocess
import sys
import threading
import shutil
import time


class ConsoleLog:
    def __init__(self, root):
        folder = Path(root) / 'runtime' / 'logs'
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / (datetime.now().strftime('agent-%Y%m%d-%H%M%S-%f') + '.log')
        self.path.touch()
        self.viewer = None
        self.lock = threading.Lock()
        self.editing = False
        self.input_buffer = ''
        self.input_prompt = 'Agent > '

    def emit(self, message='', **kwargs):
        with self.lock:
            if self.editing:
                print('\r'+' '*max(1,shutil.get_terminal_size().columns-1)+'\r',end='',flush=True)
            print(message, **kwargs)
            if self.editing: print(self.input_prompt+self.input_buffer,end='',flush=True)
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(datetime.now().strftime('[%H:%M:%S] ') + str(message) + '\n')

    def read_line(self, prompt='Agent > '):
        if os.name != 'nt' or not sys.stdin.isatty(): return input(prompt)
        import msvcrt
        with self.lock:
            self.editing=True; self.input_buffer=''; self.input_prompt=prompt
            print(prompt,end='',flush=True)
        try:
            while True:
                if not msvcrt.kbhit(): time.sleep(.02); continue
                char=msvcrt.getwch()
                if char in ('\x00','\xe0'): msvcrt.getwch(); continue
                if char=='\x03': raise KeyboardInterrupt
                if char=='\x1a': raise EOFError
                with self.lock:
                    if char in ('\r','\n'):
                        print(); return self.input_buffer
                    if char=='\b': self.input_buffer=self.input_buffer[:-1]
                    elif char.isprintable(): self.input_buffer+=char
                    print('\r'+' '*max(1,shutil.get_terminal_size().columns-1)+'\r'+prompt+self.input_buffer,end='',flush=True)
        finally:
            with self.lock: self.editing=False

    def show(self):
        if self.viewer is not None and self.viewer.poll() is None:
            return
        self.viewer = subprocess.Popen(
            [sys.executable, '-m', 'modular_agent.agent.log_viewer', str(self.path)],
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def hide(self):
        if self.viewer is not None and self.viewer.poll() is None:
            self.viewer.terminate()
            self.viewer.wait(timeout=5)
        self.viewer = None

    def close(self):
        self.hide()
