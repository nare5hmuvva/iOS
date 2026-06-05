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

    def run(cmd):
        _, out, err = c.exec_command(cmd, timeout=30)
        o = out.read().decode(errors='replace').strip()
        e = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        if txt: print(txt[:400])
        return o

    print('[dpkg -L ldid]')
    run(S + 'dpkg -L ldid 2>/dev/null')
    print('[find ldid]')
    run(S + 'find /usr /var/jb /bin /sbin -name ldid 2>/dev/null | head -5')
    print('[which ldid]')
    run(S + 'which ldid 2>/dev/null || echo not_in_path')
    c.close()
finally:
    fwd.terminate()
