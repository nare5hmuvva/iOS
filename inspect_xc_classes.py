"""Inspect XCSynthesizedEventRecord and XCPointerEventPath methods via ctypes."""
import subprocess, sys, time, paramiko

INSPECT_PY = r"""
import ctypes

libobjc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
libobjc.objc_msgSend.restype = ctypes.c_void_p
libobjc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
libobjc.sel_registerName.restype = ctypes.c_void_p
libobjc.sel_registerName.argtypes = [ctypes.c_char_p]
libobjc.objc_getClass.restype = ctypes.c_void_p
libobjc.objc_getClass.argtypes = [ctypes.c_char_p]
libobjc.class_copyMethodList.restype = ctypes.c_void_p
libobjc.class_copyMethodList.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
libobjc.method_getName.restype = ctypes.c_void_p
libobjc.method_getName.argtypes = [ctypes.c_void_p]
libobjc.sel_getName.restype = ctypes.c_char_p
libobjc.sel_getName.argtypes = [ctypes.c_void_p]
libobjc.free.restype = None
libobjc.free.argtypes = [ctypes.c_void_p]

# objc_getMetaClass for class methods
libobjc.objc_getMetaClass.restype = ctypes.c_void_p
libobjc.objc_getMetaClass.argtypes = [ctypes.c_char_p]

for fw in [
    '/Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport',
    '/Developer/Library/PrivateFrameworks/XCUIAutomation.framework/XCUIAutomation',
    '/Developer/Library/PrivateFrameworks/XCTestCore.framework/XCTestCore',
]:
    ctypes.CDLL(fw, ctypes.RTLD_GLOBAL)

def list_methods(cls_ptr, label):
    count = ctypes.c_uint(0)
    methods_ptr = libobjc.class_copyMethodList(cls_ptr, ctypes.byref(count))
    print(f'{label} ({count.value} methods):')
    if methods_ptr and count.value:
        method_array = (ctypes.c_void_p * count.value).from_address(methods_ptr)
        for m in method_array:
            sel_ptr = libobjc.method_getName(m)
            name = libobjc.sel_getName(sel_ptr)
            if name:
                print(f'  {name.decode()}')
        libobjc.free(methods_ptr)

def sel(name): return libobjc.sel_registerName(name.encode())
def cls(name): return libobjc.objc_getClass(name.encode())
def metacls(name): return libobjc.objc_getMetaClass(name.encode())

rec_cls = cls('XCSynthesizedEventRecord')
path_cls = cls('XCPointerEventPath')
session_cls = cls('XCTAutomationSession')
runner_cls = cls('XCTRunnerDaemonSession')

print(f'XCSynthesizedEventRecord: {rec_cls:#x}' if rec_cls else 'XCSynthesizedEventRecord: NOT FOUND')
print(f'XCPointerEventPath: {path_cls:#x}' if path_cls else 'XCPointerEventPath: NOT FOUND')
print(f'XCTAutomationSession: {session_cls:#x}' if session_cls else 'XCTAutomationSession: NOT FOUND')
print(f'XCTRunnerDaemonSession: {runner_cls:#x}' if runner_cls else 'XCTRunnerDaemonSession: NOT FOUND')
print()

if path_cls:
    list_methods(path_cls, 'XCPointerEventPath instance methods')
    list_methods(metacls('XCPointerEventPath'), 'XCPointerEventPath class methods')
    print()

if rec_cls:
    list_methods(rec_cls, 'XCSynthesizedEventRecord instance methods')
    list_methods(metacls('XCSynthesizedEventRecord'), 'XCSynthesizedEventRecord class methods')
    print()

if session_cls:
    list_methods(session_cls, 'XCTAutomationSession instance methods')
    list_methods(metacls('XCTAutomationSession'), 'XCTAutomationSession class methods')
    print()

if runner_cls:
    list_methods(runner_cls, 'XCTRunnerDaemonSession instance methods')
    list_methods(metacls('XCTRunnerDaemonSession'), 'XCTRunnerDaemonSession class methods')
    print()
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
    with sftp.open('/tmp/inspect_xc.py', 'w') as f: f.write(INSPECT_PY)
    sftp.close()

    run('echo one | /var/jb/usr/bin/sudo -S -p "" python3 /tmp/inspect_xc.py 2>&1',
        'XC class method inspection', timeout=30)

    c.close()
finally:
    fwd.terminate()
