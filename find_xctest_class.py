"""Find actual class names in XCTAutomationSupport on this iOS 15 device."""
import subprocess, sys, time, paramiko

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

    # List ObjC classes in XCTAutomationSupport
    run('nm /Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport '
        '2>/dev/null | grep -i "OBJC_CLASS\\|event\\|tap\\|touch\\|generator" | head -30',
        'XCTAutomationSupport classes (nm)')

    run('otool -ov /Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport '
        '2>/dev/null | grep "^.*name.*$" | grep -i "event\\|tap\\|touch\\|generator\\|synth" | head -20',
        'otool classes')

    # Also check what testmanagerd is
    run('ps -A | grep testmanagerd | grep -v grep', 'testmanagerd pid')
    run('ls /Developer/usr/lib/', 'Developer usr lib')
    run('ls /Developer/Library/PrivateFrameworks/', 'Developer PrivateFrameworks')

    # Check XCTest framework
    run('nm /Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport '
        '2>/dev/null | grep "T _OBJC_CLASS" | head -30',
        'all ObjC classes in XCTAutomationSupport')

    # Try the XCTestBundleInject.dylib too
    run('nm /Developer/usr/lib/libXCTestBundleInject.dylib 2>/dev/null | grep "T _OBJC_CLASS" | head -20',
        'XCTestBundleInject classes')

    c.close()
finally:
    fwd.terminate()
