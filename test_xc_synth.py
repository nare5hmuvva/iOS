"""Test XCSynthesizedEventRecord + XCPointerEventPath on-device via Python/ctypes."""
import subprocess, sys, time, paramiko

SYNTH_TEST_PY = r"""
import ctypes, ctypes.util

# Load ObjC runtime and frameworks
libobjc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
libobjc.objc_msgSend.restype = ctypes.c_void_p
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
libobjc.sel_registerName.restype = ctypes.c_void_p
libobjc.sel_registerName.argtypes = [ctypes.c_char_p]
libobjc.objc_getClass.restype = ctypes.c_void_p
libobjc.objc_getClass.argtypes = [ctypes.c_char_p]

# Load frameworks
for fw in [
    '/Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport',
    '/Developer/Library/PrivateFrameworks/XCUIAutomation.framework/XCUIAutomation',
    '/Developer/Library/PrivateFrameworks/XCTestCore.framework/XCTestCore',
]:
    r = ctypes.CDLL(fw, ctypes.RTLD_GLOBAL)
    print(f'Loaded {fw.split("/")[-1]}: {r._handle:#x}')

def sel(name): return libobjc.sel_registerName(name.encode())
def cls(name): return libobjc.objc_getClass(name.encode())
def msg(obj, sel_name, *args):
    f = libobjc.objc_msgSend
    return f(obj, sel(sel_name), *args)

# Check XCSynthesizedEventRecord
rec_cls = cls('XCSynthesizedEventRecord')
print(f'XCSynthesizedEventRecord: {rec_cls:#x}' if rec_cls else 'XCSynthesizedEventRecord: NOT FOUND')

path_cls = cls('XCPointerEventPath')
print(f'XCPointerEventPath: {path_cls:#x}' if path_cls else 'XCPointerEventPath: NOT FOUND')

# Check XCTAutomationSession
session_cls = cls('XCTAutomationSession')
print(f'XCTAutomationSession: {session_cls:#x}' if session_cls else 'XCTAutomationSession: NOT FOUND')

# Check XCTRunnerDaemonSession
runner_cls = cls('XCTRunnerDaemonSession')
print(f'XCTRunnerDaemonSession: {runner_cls:#x}' if runner_cls else 'XCTRunnerDaemonSession: NOT FOUND')

if not (rec_cls and path_cls):
    print('Missing required classes')
    import sys; sys.exit(1)

# --- Try synthesizing a tap at (187, 333) ---
# Step 1: Create XCSynthesizedEventRecord
# alloc
libobjc.objc_msgSend.restype = ctypes.c_void_p
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
rec = msg(rec_cls, 'alloc')
print(f'record alloc: {rec:#x}' if rec else 'record alloc: FAILED')

# init: -initWithName:interfaceOrientation:
libobjc.objc_msgSend.restype = ctypes.c_void_p
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]

# Create NSString for name
libobjc.objc_getClass.restype = ctypes.c_void_p
nsstring_cls = cls('NSString')
libobjc.objc_msgSend.restype = ctypes.c_void_p
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
name_str = msg(nsstring_cls, 'stringWithUTF8String:', b'Tap')
print(f'name_str: {name_str:#x}' if name_str else 'name_str: FAILED')

libobjc.objc_msgSend.restype = ctypes.c_void_p
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
rec = msg(rec, 'initWithName:interfaceOrientation:', name_str, 1)  # orientation: portrait=1
print(f'record init: {rec:#x}' if rec else 'record init: FAILED')

if not rec:
    print('initWithName failed')
    import sys; sys.exit(1)

# Step 2: Create XCPointerEventPath
# Try: +pointerEventPathForTouchAtPoint:offset: (class method)
class CGPoint(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]

pt = CGPoint(187.0, 333.0)

libobjc.objc_msgSend.restype = ctypes.c_void_p
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, CGPoint, ctypes.c_double]

path = msg(path_cls, 'pointerEventPathForTouchAtPoint:offset:', pt, 0.0)
print(f'path (class method): {path:#x}' if path else 'path class method: FAILED')

if not path:
    # Try: alloc + initForTouchAtPoint:offset:
    libobjc.objc_msgSend.restype = ctypes.c_void_p
    libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    path = msg(path_cls, 'alloc')
    if path:
        libobjc.objc_msgSend.restype = ctypes.c_void_p
        libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, CGPoint, ctypes.c_double]
        path = msg(path, 'initForTouchAtPoint:offset:', pt, 0.0)
    print(f'path (alloc+init): {path:#x}' if path else 'path alloc+init: FAILED')

if not path:
    print('Could not create XCPointerEventPath')
    import sys; sys.exit(1)

# Step 3: touchDown (not always needed, some init methods include touch-down)
# Try -touchUpAtPoint:atOffset:
libobjc.objc_msgSend.restype = ctypes.c_void_p
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, CGPoint, ctypes.c_double]
msg(path, 'touchUpAtPoint:atOffset:', pt, 0.1)
print('touchUpAtPoint:atOffset: called')

# Step 4: addPointerEventPath:
libobjc.objc_msgSend.restype = ctypes.c_void_p
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
msg(rec, 'addPointerEventPath:', path)
print('addPointerEventPath: called')

# Step 5: Synthesize â€” try XCTAutomationSession
if session_cls:
    libobjc.objc_msgSend.restype = ctypes.c_void_p
    libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    session = msg(session_cls, 'sharedSession')
    print(f'XCTAutomationSession.sharedSession: {session:#x}' if session else 'sharedSession: nil')
    if session:
        # Try synthesizeEvent:completion:
        # We'll use a simple null block for now
        libobjc.objc_msgSend.restype = ctypes.c_void_p
        libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        msg(session, 'synthesizeEvent:completion:', rec, None)
        print('synthesizeEvent:completion: called')

if runner_cls:
    libobjc.objc_msgSend.restype = ctypes.c_void_p
    libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    runner = msg(runner_cls, 'sharedSession')
    print(f'XCTRunnerDaemonSession.sharedSession: {runner:#x}' if runner else 'sharedSession: nil')
    if runner:
        libobjc.objc_msgSend.restype = ctypes.c_void_p
        libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        msg(runner, 'synthesizeEvent:completion:', rec, None)
        print('XCTRunnerDaemonSession synthesizeEvent called')

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
        if e: print('  err:', e[:300])
        print()
        return o

    sftp = c.open_sftp()
    with sftp.open('/tmp/synth_test.py', 'w') as f: f.write(SYNTH_TEST_PY)
    sftp.close()

    print('>>> WATCH YOUR SCREEN â€” should tap center <<<')
    run('echo one | /var/jb/usr/bin/sudo -S -p "" python3 /tmp/synth_test.py 2>&1',
        'XCSynthesizedEventRecord tap test', timeout=30)

    c.close()
finally:
    fwd.terminate()
