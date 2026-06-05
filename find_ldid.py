import subprocess, sys, time, paramiko

fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', '2224', '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)

try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=2224, username='mobile', password='one', timeout=12)
    S = 'echo one | /var/jb/usr/bin/sudo -S -p "" '

    def run(cmd, label=''):
        _, out, err = c.exec_command(cmd, timeout=30)
        rc = out.channel.recv_exit_status()
        o = out.read().decode(errors='replace').strip()
        e = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        print(f'[{label or cmd[:60]}]')
        if txt: print('  ' + txt[:400].replace('\n', '\n  '))
        return o

    run(S + 'find /var/jb /usr /bin -name ldid 2>/dev/null', 'find ldid')
    run(S + 'dpkg -l | grep ldid', 'ldid installed?')
    run(S + 'apt-cache search ldid 2>/dev/null', 'apt ldid')
    run(S + '/var/jb/usr/bin/apt-get install -y --allow-unauthenticated ldid 2>&1 | tail -5',
        'install ldid')
    run(S + 'find /var/jb -name ldid 2>/dev/null', 'ldid after install')
    c.close()
finally:
    fwd.terminate()
