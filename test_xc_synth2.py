"""Test XCSynthesizedEventRecord tap using correct method names discovered via inspection."""
import subprocess, sys, time, paramiko

SYNTH2_PY = r"""
import ctypes

libobjc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
libobjc.objc_msgSend.restype = ctypes.c_void_p
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
libobjc.sel_registerName.restype = ctypes.c_void_p
libobjc.sel_registerName.argtypes = [ctypes.c_char_p]
libobjc.objc_getClass.restype = ctypes.c_void_p
libobjc.objc_getClass.argtypes = [ctypes.c_char_p]

for fw in [
    '/Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport',
    '/Developer/Library/PrivateFrameworks/XCUIAutomation.framework/XCUIAutomation',
    '/Developer/Library/PrivateFrameworks/XCTestCore.framework/XCTestCore',
]:
    ctypes.CDLL(fw, ctypes.RTLD_GLOBAL)

def sel(name): return libobjc.sel_registerName(name.encode())
def cls(name): return libobjc.objc_getClass(name.encode())

def msg0(obj, sel_name):
    libobjc.objc_msgSend.restype = ctypes.c_void_p
    libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    return libobjc.objc_msgSend(obj, sel(sel_name))

def msg1ptr(obj, sel_name, arg):
    libobjc.objc_msgSend.restype = ctypes.c_void_p
    libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    return libobjc.objc_msgSend(obj, sel(sel_name), arg)

def msg2ptrlong(obj, sel_name, arg1, arg2):
    libobjc.objc_msgSend.restype = ctypes.c_void_p
    libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
    return libobjc.objc_msgSend(obj, sel(sel_name), arg1, arg2)

class CGPoint(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]

def msg_point_double(obj, sel_name, pt, d):
    libobjc.objc_msgSend.restype = ctypes.c_void_p
    libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, CGPoint, ctypes.c_double]
    return libobjc.objc_msgSend(obj, sel(sel_name), pt, d)

def msg_double(obj, sel_name, d):
    libobjc.objc_msgSend.restype = ctypes.c_void_p
    libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double]
    return libobjc.objc_msgSend(obj, sel(sel_name), d)

def msg_ptr_ptr(obj, sel_name, a, b):
    libobjc.objc_msgSend.restype = ctypes.c_void_p
    libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    return libobjc.objc_msgSend(obj, sel(sel_name), a, b)

def msg_bool_ret(obj, sel_name, arg):
    libobjc.objc_msgSend.restype = ctypes.c_bool
    libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    return libobjc.objc_msgSend(obj, sel(sel_name), arg)

rec_cls = cls('XCSynthesizedEventRecord')
path_cls = cls('XCPointerEventPath')
runner_cls = cls('XCTRunnerDaemonSession')

print(f'rec_cls: {rec_cls:#x}' if rec_cls else 'rec_cls: NONE')
print(f'path_cls: {path_cls:#x}' if path_cls else 'path_cls: NONE')
print(f'runner_cls: {runner_cls:#x}' if runner_cls else 'runner_cls: NONE')

# --- Step 1: XCSynthesizedEventRecord ---
nsstring_cls = cls('NSString')
libobjc.objc_msgSend.restype = ctypes.c_void_p
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
name_str = libobjc.objc_msgSend(nsstring_cls, sel('stringWithUTF8String:'), b'Tap')

rec = msg0(rec_cls, 'alloc')
rec = msg2ptrlong(rec, 'initWithName:interfaceOrientation:', name_str, 1)
print(f'record: {rec:#x}' if rec else 'record: FAILED')

if not rec:
    import sys; sys.exit(1)

# --- Step 2: XCPointerEventPath via alloc + initForTouchAtPoint:offset: ---
pt = CGPoint(187.0, 333.0)

path = msg0(path_cls, 'alloc')
print(f'path alloc: {path:#x}' if path else 'path alloc: FAILED')

path = msg_point_double(path, 'initForTouchAtPoint:offset:', pt, 0.0)
print(f'path init: {path:#x}' if path else 'path init: FAILED')

if not path:
    import sys; sys.exit(1)

# --- Step 3: pressDown then liftUp ---
msg_double(path, 'pressDownAtOffset:', 0.0)
print('pressDownAtOffset: 0.0 done')

msg_double(path, 'liftUpAtOffset:', 0.1)
print('liftUpAtOffset: 0.1 done')

# --- Step 4: addPointerEventPath to record ---
msg1ptr(rec, 'addPointerEventPath:', path)
print('addPointerEventPath: done')

# --- Step 5: synthesizeWithError: ---
print('Trying synthesizeWithError:...')
err_ptr = ctypes.c_void_p(0)
err_ref = ctypes.byref(err_ptr)
libobjc.objc_msgSend.restype = ctypes.c_bool
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
result = libobjc.objc_msgSend(rec, sel('synthesizeWithError:'), None)
print(f'synthesizeWithError: returned {result}')
if result:
    print('SUCCESS - tap should have fired!')
else:
    print('synthesizeWithError: returned NO/nil')

# --- Step 6: Also try XCTRunnerDaemonSession.sharedSession ---
print()
print('Trying XCTRunnerDaemonSession.sharedSession...')
runner = msg0(runner_cls, 'sharedSession')
print(f'sharedSession: {runner:#x}' if runner else 'sharedSession: nil')

if runner:
    msg_ptr_ptr(runner, 'synthesizeEvent:completion:', rec, None)
    print('XCTRunnerDaemonSession synthesizeEvent:completion: called')

import time; time.sleep(1)
print('DONE')
"""

fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', '2222', '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
time.sleep(2)

try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=2222, username='mobile', password='one', timeout=10)

    def run(cmd, label='', timeout=30):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        print(f'--- {label} ---')
        if o: print(o)
        if e: print('  err:', e[:500])
        print()
        return o

    sftp = c.open_sftp()
    with sftp.open('/tmp/synth2.py', 'w') as f: f.write(SYNTH2_PY)
    sftp.close()

    print('>>> WATCH YOUR SCREEN - should tap at center <<<')
    run('echo one | /var/jb/usr/bin/sudo -S -p "" python3 /tmp/synth2.py 2>&1',
        'XCSynthesizedEventRecord corrected tap test', timeout=30)

    c.close()
finally:
    fwd.terminate()
