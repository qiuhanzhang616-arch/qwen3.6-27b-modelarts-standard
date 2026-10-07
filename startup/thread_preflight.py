"""Probe thread creation; add an errno-only clone3 deny rule if required.

Existing seccomp rules remain active. The denied syscall remains denied.
No compatibility filter is applied when threads already work.
"""
import ctypes, errno, platform, threading

def probe():
    worker=threading.Thread(target=lambda:None)
    worker.start()
    worker.join(5)
    assert not worker.is_alive(), 'thread probe did not complete'

def ensure_threads():
    try:
        probe()
        return {'thread_probe':'passed','compatibility_filter_applied':False}
    except RuntimeError:
        if platform.machine() not in ('aarch64','arm64'):raise
    libc=ctypes.CDLL(None,use_errno=True)
    libc.syscall.restype=ctypes.c_long
    libc.prctl.restype=ctypes.c_int
    libc.prctl.argtypes=[ctypes.c_int]+[ctypes.c_ulong]*4
    ctypes.set_errno(0)
    result=libc.syscall(ctypes.c_long(435),ctypes.c_void_p(0),ctypes.c_size_t(88))
    before=ctypes.get_errno()
    if (result,before)!=(-1,errno.EPERM):
        raise RuntimeError(f'Thread failure is not verified clone3 EPERM: {result}/{before}')
    class Filter(ctypes.Structure):
        _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(Filter))]
    rules=(Filter*6)(Filter(0x20,0,0,4),Filter(0x15,0,3,0xC00000B7),Filter(0x20,0,0,0),Filter(0x15,0,1,435),Filter(0x06,0,0,0x00050000|errno.ENOSYS),Filter(0x06,0,0,0x7FFF0000))
    program=Program(len(rules),rules)
    assert libc.prctl(38,1,0,0,0)==0,'no_new_privs failed'
    assert libc.prctl(22,2,ctypes.addressof(program),0,0)==0,'additive deny filter failed'
    ctypes.set_errno(0)
    result=libc.syscall(ctypes.c_long(435),ctypes.c_void_p(0),ctypes.c_size_t(88))
    after=ctypes.get_errno()
    assert (result,after)==(-1,errno.ENOSYS)
    probe()
    return {'thread_probe':'passed','compatibility_filter_applied':True,'clone3_errno_before':before,'clone3_errno_after':after,'inherited_seccomp':'preserved','clone3':'still denied'}
