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

    cmds = [
        # Check frida-helper
        'echo one | /var/jb/usr/bin/sudo -S -p "" ls -la /var/jb/usr/lib/frida/ 2>/dev/null',
        # Also symlink helper
        'echo one | /var/jb/usr/bin/sudo -S -p "" sh -c \''
        'PROCURSUS=$(realpath /var/jb); '
        'DOUBLED="${PROCURSUS}${PROCURSUS}"; '
        'mkdir -p "${DOUBLED}/usr/lib/frida/"; '
        'for f in /var/jb/usr/lib/frida/*; do ln -sf "$f" "${DOUBLED}/usr/lib/frida/$(basename $f)" 2>/dev/null; done; '
        'ls -la "${DOUBLED}/usr/lib/frida/"; '
        '\'',
        # Kill and restart frida-server
        'echo one | /var/jb/usr/bin/sudo -S -p "" killall frida-server 2>/dev/null; sleep 1',
        'echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/sbin/frida-server -D &',
        'sleep 2',
        'ps aux | grep frida-server | grep -v grep',
    ]
    for cmd in cmds:
        _, out, err = c.exec_command(cmd)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        if o: print(o)
        if e: print('err:', e[:200])

    c.close()
    print('[+] frida-server restarted')
finally:
    fwd.terminate()
