"""Find which process has com.apple.hid.manager.user-access-service entitlement."""
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
        if e: print('  err:', e[:200])
        print()
        return o

    # Check SpringBoard full HID entitlements
    run('ldid -e /System/Library/CoreServices/SpringBoard.app/SpringBoard 2>&1 | grep -i hid',
        'SpringBoard HID entitlements')

    # Check backboardd
    run('ldid -e /usr/libexec/backboardd 2>&1 | grep -iE "hid|dispatch|user-access"',
        'backboardd HID entitlements')
    run('ps -A | grep backboard | grep -v grep', 'backboardd pid')

    # Check hidd (HID daemon)
    run('ldid -e /usr/libexec/hidd 2>&1 | grep -iE "hid|dispatch|user-access"',
        'hidd HID entitlements')
    run('ps -A | grep hidd | grep -v grep', 'hidd pid')

    # Find any binary with user-access-service entitlement
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"for f in /usr/libexec/* /usr/bin/* /System/Library/CoreServices/*.app/*/; do '
        'ldid -e \\"$f\\" 2>/dev/null | grep -q user-access-service && echo \\"$f\\"; done" 2>/dev/null | head -10',
        'find user-access-service owners', timeout=20)

    # Also try running tap_hid directly with our entitlements from trusted path
    # (already have com.apple.hid.manager.user-access-service from ldid)
    # and see if maybe the coordinates are the issue â€” test at pixel coords
    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/tap_hid tap 375 667; echo exit:$?',
        'tap_hid at full screen corner (375,667)')

    # Test at known UI element locations â€” try tapping where UI buttons clearly are
    # SpringBoard home screen: icons at roughly top-left of screen
    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/tap_hid tap 50 100; echo exit:$?',
        'tap_hid at top-left (50,100)')

    # Now check: does backboardd have user-access-service?
    run('ldid -e /usr/libexec/backboardd 2>&1 | head -50', 'backboardd full ents')

    c.close()
finally:
    fwd.terminate()
