"""Start testmanagerd, retry XCEventGenerator, and also inject into backboardd."""
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

    # Start testmanagerd
    run('echo one | /var/jb/usr/bin/sudo -S -p "" launchctl start com.apple.testmanagerd 2>&1',
        'start testmanagerd')
    time.sleep(2)
    run('ps -A | grep testmanagerd | grep -v grep', 'testmanagerd running?')

    # Respring to get fresh SpringBoard
    run('echo one | /var/jb/usr/bin/sudo -S -p "" killall -9 SpringBoard', 'respring')
    print('Waiting 8s...')
    time.sleep(8)

    sb_line = run('ps -A | grep SpringBoard | grep -v grep', 'sb pid')
    sb_pid = None
    for line in sb_line.splitlines():
        parts = line.split()
        if parts:
            try: sb_pid = int(parts[0]); break
            except ValueError: pass
    print(f'>>> SpringBoard PID: {sb_pid}')

    # Check testmanagerd after respring
    run('ps -A | grep testmanagerd | grep -v grep', 'testmanagerd after respring')

    if sb_pid:
        run('echo one | /var/jb/usr/bin/sudo -S -p "" rm -f /tmp/taphook.log /tmp/tap_sock', 'clean')
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {sb_pid} /var/jb/usr/lib/tap_hook.dylib 2>&1',
            'inject xctest hook into SpringBoard')
        time.sleep(2)

        run('cat /tmp/taphook.log', 'init log (XCEventGenerator status)')

        if 'null' not in open('/dev/null').read():  # always true â€” just a marker
            print('=== Test XCEventGenerator ===')
            run('echo one | /var/jb/usr/bin/sudo -S -p "" '
                '/var/jb/usr/bin/tap_client tap 187 333; echo exit:$?',
                'tap via XCEventGenerator', timeout=15)
            run('cat /tmp/taphook.log', 'log after tap')

    # Also try injecting into backboardd with IOHIDEvent dylib (v4 - pure C, logging)
    bb_line = run('ps -A | grep backboard | grep -v grep', 'backboardd pid')
    bb_pid = None
    for line in bb_line.splitlines():
        parts = line.split()
        if parts:
            try: bb_pid = int(parts[0]); break
            except ValueError: pass
    print(f'>>> backboardd PID: {bb_pid}')

    if bb_pid:
        # Use the IOHIDEvent dylib (v4 with logging) â€” injecting into backboardd this time
        run('echo one | /var/jb/usr/bin/sudo -S -p "" rm -f /tmp/taphook.log /tmp/tap_sock', 'clean2')
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {bb_pid} /var/jb/usr/lib/tap_hook.dylib 2>&1',
            f'inject xctest dylib into backboardd({bb_pid})')
        # Note: xctest dylib tries to load XCTAutomationSupport â€” likely no good in backboardd
        # Let's check the log
        time.sleep(2)
        run('cat /tmp/taphook.log', 'backboardd xctest init log')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" '
            '/var/jb/usr/bin/tap_client tap 187 333; echo exit:$?',
            'tap from backboardd context', timeout=15)
        run('cat /tmp/taphook.log', 'log after backboardd tap')

    c.close()
finally:
    fwd.terminate()
