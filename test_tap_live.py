"""Quick live test: tap the center of the screen and verify the output."""
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

    def run(cmd, label='', timeout=15):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        print(f'--- {label} ---')
        if o: print(o)
        if e: print('  err:', e[:300])
        print()
        return o

    # Confirm binary + entitlements
    run('ldid -e /var/jb/usr/bin/tap_hid 2>&1', 'tap_hid entitlements')

    # Tap center screen â€” watch your phone!
    print('>>> TAPPING CENTER OF SCREEN (187, 333) â€” watch the device <<<')
    run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/tap_hid tap 187 333; echo exit:$?',
        'tap center (187,333)')

    time.sleep(1)

    # Tap home button area (bottom center)
    print('>>> TAPPING BOTTOM (187, 640) <<<')
    run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/tap_hid tap 187 640; echo exit:$?',
        'tap bottom (187,640)')

    time.sleep(1)

    # Swipe up from bottom (home gesture on iOS 15)
    print('>>> SWIPE UP from bottom <<<')
    run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/tap_hid swipe 187 640 187 100; echo exit:$?',
        'swipe up')

    c.close()
finally:
    fwd.terminate()
