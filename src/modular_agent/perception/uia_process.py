"""Resident read-only UIA subprocess with per-request timeout and restart isolation."""
import json
import os
import queue
import subprocess
import sys
import threading


class UIAProcess:
    def __init__(self):
        self.process=None
        self.responses=None
        self.lock=threading.RLock()

    def _start(self):
        options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        self.process=subprocess.Popen([sys.executable,'-m','modular_agent.perception.uia_worker','--serve'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',bufsize=1,**options)
        self.responses=queue.Queue()
        pipe=self.process.stdout
        responses=self.responses
        def read():
            try:
                for line in pipe: responses.put(line)
            finally:
                responses.put(None)
                pipe.close()
        threading.Thread(target=read,name='uia-output',daemon=True).start()

    def request(self,handles,timeout=4):
        with self.lock:
            if self.process is None or self.process.poll() is not None: self._start()
            try:
                self.process.stdin.write(json.dumps({'handles':handles})+'\n')
                self.process.stdin.flush()
                line=self.responses.get(timeout=timeout)
                if line is None: raise RuntimeError('UI Automation worker exited')
                reply=json.loads(line)
                if 'error' in reply: raise RuntimeError('UI Automation worker failed: '+reply['error'])
                return reply
            except queue.Empty:
                self.close()
                raise TimeoutError('UI Automation timed out; worker stopped, next request restarts it') from None
            except Exception:
                self.close()
                raise

    def close(self):
        with self.lock:
            process=self.process
            self.process=None
            self.responses=None
            if process is not None:
                if process.poll() is None: process.terminate()
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=2)
                if process.stdin: process.stdin.close()
