"""
Test: run tap_hid inside SpringBoard's bootstrap context via 'launchctl bsexec'.
IOHIDEventSystemClientDispatchEvent only works from within the GUI bootstrap â€”
not from an SSH session which is in the system/session bootstrap context.
"""
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

    # Find SpringBoard PID using ps -A (no awk needed)
    out = run('ps -A | grep SpringBoard | grep -v grep', 'ps SpringBoard')
    sb_pid = None
    for line in out.strip().splitlines():
        parts = line.split()
        if parts:
            try:
                sb_pid = int(parts[0])
                print(f'>>> SpringBoard PID = {sb_pid}')
                break
            except ValueError:
                pass

    if not sb_pid:
        print('ERROR: could not find SpringBoard PID')
    else:
        # Test 1: direct run (current broken approach â€” SSH context)
        print('=== Test 1: SSH context (broken) ===')
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/tap_hid tap 187 333; echo exit:$?',
            'tap via SSH context')

        time.sleep(1)

        # Test 2: bsexec inside SpringBoard bootstrap (should work)
        print('=== Test 2: launchctl bsexec into SpringBoard bootstrap ===')
        print('>>> WATCH THE DEVICE SCREEN <<<')
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'launchctl bsexec {sb_pid} /var/jb/usr/bin/tap_hid tap 187 333; echo exit:$?',
            f'tap via bsexec(SpringBoard={sb_pid})')

        time.sleep(1)

        # Test 3: swipe up (home gesture)
        print('>>> SWIPE UP (home gesture) â€” watch screen <<<')
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'launchctl bsexec {sb_pid} /var/jb/usr/bin/tap_hid swipe 187 600 187 150; echo exit:$?',
            'swipe up via bsexec')

    c.close()
finally:
    fwd.terminate()
