"""Find usable touch class in XCUIAutomation.framework, try starting testmanagerd."""
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

    def run(cmd, label='', timeout=20):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        print(f'--- {label} ---')
        if o: print(o)
        if e: print('  err:', e[:300])
        print()
        return o

    # Check XCUIAutomation framework for touch classes
    run('strings /Developer/Library/PrivateFrameworks/XCUIAutomation.framework/XCUIAutomation '
        '2>/dev/null | grep -iE "XC.*[Ee]vent|XC.*[Tt]ouch|XC.*[Tt]ap|Automati" | head -20',
        'XCUIAutomation strings')

    run('strings /Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport '
        '2>/dev/null | grep -iE "XC.*[Ee]vent|XC.*[Tt]ouch|XC.*[Tt]ap|Synthes" | head -20',
        'XCTAutomationSupport strings')

    # Find testmanagerd binary
    run('find /Developer /System/Library/PrivateFrameworks -name "testmanagerd" 2>/dev/null',
        'find testmanagerd binary')
    run('ls /Developer/usr/bin/ 2>/dev/null', 'Developer usr bin')
    run('find /usr /System -name "testmanagerd*" 2>/dev/null | head -5', 'find testmanagerd system')

    # Try to start testmanagerd via launchctl
    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        'launchctl list 2>/dev/null | grep -i "test\\|xctest\\|manage" | head -10',
        'launchctl xctest services')

    # Check which DTX services are running (testmanagerd uses DTX)
    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        'launchctl list 2>/dev/null | grep -i "dtx\\|developer\\|instruments" | head -10',
        'launchctl developer services')

    # NEW APPROACH: Check if backboardd (PID 591) can receive IOHIDEvent injection
    # backboardd has com.apple.hid.multitouch.user-access â€” inject there
    run('ps -A | grep backboard | grep -v grep', 'backboardd pid')

    # Also â€” try pymobiledevice3's native DVT tap if available
    run('python3 -c "import pymobiledevice3; print(pymobiledevice3.__version__)"', 'pymobiledevice3 version')

    c.close()
finally:
    fwd.terminate()
