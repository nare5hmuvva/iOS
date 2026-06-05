"""Enumerate XC* classes loaded after dlopen via ObjC runtime + ctypes."""
import subprocess, sys, time, paramiko

LIST_CLASSES_PY = r"""
import ctypes, sys

libobjc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')

# Load frameworks
for fw in [
    '/Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport',
    '/Developer/Library/PrivateFrameworks/XCUIAutomation.framework/XCUIAutomation',
    '/Developer/Library/PrivateFrameworks/XCTestCore.framework/XCTestCore',
]:
    h = ctypes.CDLL(fw)
    print(f'Loaded: {fw} -> {h}')

# Get all classes
libobjc.objc_getClassList.restype = ctypes.c_int
libobjc.objc_getClassList.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
count = libobjc.objc_getClassList(None, 0)
print(f'Total classes: {count}')
buf = (ctypes.c_void_p * count)()
libobjc.objc_getClassList(buf, count)

libobjc.class_getName.restype = ctypes.c_char_p
libobjc.class_getName.argtypes = [ctypes.c_void_p]

xc_classes = []
for i in range(count):
    name = libobjc.class_getName(buf[i])
    if name and name.startswith(b'XC'):
        xc_classes.append(name.decode())

for cls in sorted(xc_classes):
    if any(k in cls.lower() for k in ['event', 'touch', 'tap', 'synth', 'pointer', 'click']):
        print(f'  MATCH: {cls}')

print('All XC* classes (first 60):')
for cls in sorted(xc_classes)[:60]:
    print(f'  {cls}')
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
    with sftp.open('/tmp/list_classes.py', 'w') as f: f.write(LIST_CLASSES_PY)
    sftp.close()

    run('echo one | /var/jb/usr/bin/sudo -S -p "" python3 /tmp/list_classes.py 2>&1',
        'XC* classes with event/touch/tap', timeout=30)

    c.close()
finally:
    fwd.terminate()
