"""Windows DPAPI credentials; never store plaintext keys in project configuration."""
from pathlib import Path
import ctypes as C
from ctypes import wintypes as W
import os
import re

class Blob(C.Structure):
    _fields_=[('size',W.DWORD),('data',C.POINTER(C.c_ubyte))]

def protect(data,*,decrypt=False):
    if os.name!='nt': raise RuntimeError('Encrypted credential files require Windows; use an environment variable elsewhere')
    crypto=C.WinDLL('crypt32',use_last_error=True)
    kernel=C.WinDLL('kernel32',use_last_error=True)
    function=crypto.CryptUnprotectData if decrypt else crypto.CryptProtectData
    function.argtypes=[C.POINTER(Blob),C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,W.DWORD,C.POINTER(Blob)]
    function.restype=W.BOOL
    kernel.LocalFree.argtypes=[C.c_void_p]
    kernel.LocalFree.restype=C.c_void_p
    buffer=(C.c_ubyte*len(data)).from_buffer_copy(data)
    source=Blob(len(data),buffer); output=Blob()
    try:
        if not function(C.byref(source),None,None,None,None,1,C.byref(output)):
            raise RuntimeError('Credential encryption/decryption failed for the current Windows user')
        return C.string_at(output.data,output.size)
    finally:
        C.memset(buffer,0,len(data))
        if output.data:
            C.memset(output.data,0,output.size)
            kernel.LocalFree(output.data)

def read_key(config):
    key=os.getenv(config.api_key_env)
    if key: return key.strip()
    if config.api_key_file:
        path=Path(config.api_key_file)
        if path.exists(): return protect(path.read_bytes(),decrypt=True).decode('utf-8').strip()
    raise RuntimeError(f'No API credential configured. Set {config.api_key_env} or configure an encrypted credential file')

def main():
    import argparse
    import getpass
    parser=argparse.ArgumentParser(description='Save an API key encrypted for the current Windows user')
    parser.add_argument('--name',default='moonshot')
    parser.add_argument('--project-root',type=Path,default=Path('.'))
    args=parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9_-]*',args.name): parser.error('Invalid credential name')
    key=getpass.getpass('API key（输入隐藏）: ').strip()
    if not key: parser.error('Key cannot be empty')
    path=args.project_root/'runtime'/'secrets'/(args.name+'.dpapi')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(protect(key.encode('utf-8')))
    print('Credential encrypted and saved; plaintext key was not written.')

if __name__=='__main__': main()
