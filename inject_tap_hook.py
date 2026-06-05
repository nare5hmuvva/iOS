"""Fix: add -framework IOKit to dylib compile, then inject into SpringBoard."""
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
        if e: print('  err:', e[:400])
        print()
        return o

    # Get SpringBoard PID
    sb_line = run('ps -A | grep SpringBoard | grep -v grep', 'sb pid')
    sb_pid = None
    for line in sb_line.splitlines():
        parts = line.split()
        if parts:
            try: sb_pid = int(parts[0]); break
            except ValueError: pass
    print(f'>>> SpringBoard PID: {sb_pid}')

    # Compile dylib â€” was missing -framework IOKit
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -shared -fPIC -framework CoreFoundation -framework IOKit '
        '-o /var/jb/usr/lib/tap_hook.dylib /tmp/tap_hook2.c 2>&1"; echo compile:$?',
        'compile tap_hook.dylib (with IOKit)', timeout=60)

    run('ls -la /var/jb/usr/lib/tap_hook.dylib', 'dylib exists')

    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/lib/tap_hook.dylib && echo signed',
        'sign dylib')

    # Inject
    if sb_pid:
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {sb_pid} /var/jb/usr/lib/tap_hook.dylib 2>&1',
            f'opainject SpringBoard({sb_pid})')

        time.sleep(2)

        run('ls -la /tmp/tap_sock 2>/dev/null || echo "no socket"', 'socket check')

        # Test tap via tap_client
        print('>>> WATCH YOUR DEVICE SCREEN <<<')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" '
            '/var/jb/usr/bin/tap_client tap 187 333; echo exit:$?',
            'tap center')
        time.sleep(1)

        run('echo one | /var/jb/usr/bin/sudo -S -p "" '
            '/var/jb/usr/bin/tap_client tap 187 600; echo exit:$?',
            'tap bottom')
        time.sleep(1)

        print('>>> SWIPE UP <<<')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" '
            '/var/jb/usr/bin/tap_client swipe 187 600 187 150; echo exit:$?',
            'swipe up')

    c.close()
finally:
    fwd.terminate()
