"""One host per Windows session; no game-process manipulation."""
import ctypes
from ctypes import wintypes as W
import os

def clear_stale_stop(path):
    """Keep stop requests made since this host started, including during imports."""
    if not path.exists():return False
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.argtypes=[];kernel.GetCurrentProcess.restype=W.HANDLE
    kernel.GetProcessTimes.argtypes=[W.HANDLE,ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME),
                                    ctypes.POINTER(W.FILETIME),ctypes.POINTER(W.FILETIME)]
    kernel.GetProcessTimes.restype=W.BOOL
    created,exited,kernel_time,user_time=(W.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(kernel.GetCurrentProcess(),ctypes.byref(created),ctypes.byref(exited),
                                  ctypes.byref(kernel_time),ctypes.byref(user_time)):
        raise ctypes.WinError(ctypes.get_last_error())
    birth=((created.dwHighDateTime<<32)|created.dwLowDateTime)-116444736000000000
    try:
        if path.stat().st_mtime_ns>=birth*100:return True
        path.unlink();return False
    except FileNotFoundError:return False

class AlreadyRunning(RuntimeError):pass

class SingleInstance:
    def __init__(self):self.kernel=None;self.handle=None
    def __enter__(self):
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateMutexW.argtypes=[W.LPVOID,W.BOOL,W.LPCWSTR];kernel.CreateMutexW.restype=W.HANDLE
        kernel.ReleaseMutex.argtypes=[W.HANDLE];kernel.ReleaseMutex.restype=W.BOOL
        kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL
        name='Local\\DLTB_AutoLoot_Resident_'+os.environ.get('USERNAME','user')
        ctypes.set_last_error(0)
        handle=kernel.CreateMutexW(None,True,name)
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error()==183:
            kernel.CloseHandle(handle)
            raise AlreadyRunning('AutoLoot est deja actif dans cette session Windows.')
        self.kernel=kernel;self.handle=handle
        return self
    def __exit__(self,*ignored):
        if self.handle:
            self.kernel.ReleaseMutex(self.handle);self.kernel.CloseHandle(self.handle);self.handle=None
