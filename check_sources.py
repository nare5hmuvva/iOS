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
        _, out, err = c.exec_command(cmd, timeout=60)
        rc = out.channel.recv_exit_status()
        o = out.read().decode(errors='replace').strip()
        e = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        print(f'[{label or cmd[:50]}]')
        if txt: print('  ' + txt[:600].replace('\n', '\n  '))
        return o

    run(S + 'find /var/jb/etc/apt /etc/apt -name "*.list" 2>/dev/null', 'apt list files')
    run(S + 'ls /var/jb/etc/apt/sources.list.d/ 2>/dev/null', 'sources.list.d')
    run(S + 'cat /var/jb/etc/apt/sources.list.d/*.list 2>/dev/null', 'sources contents')
    run(S + 'apt-cache search frida 2>/dev/null | head -10', 'apt frida')
    run(S + 'apt-cache search appsync 2>/dev/null | head -5', 'apt appsync')
    run(S + 'apt-cache search appinst 2>/dev/null | head -5', 'apt appinst')
    # Check if python or fetch is available for downloading
    run('which python3 /var/jb/usr/bin/python3 /usr/bin/python3 2>/dev/null | head -1', 'python3')
    run('which fetch /var/jb/usr/bin/fetch 2>/dev/null', 'fetch')
    run(S + 'dpkg -l | grep -E "wget|curl|fetch" 2>/dev/null', 'download tools dpkg')
    # Check usbfluxd / iproxyold paths
    run(S + 'apt-cache show ellekit | grep -E "Depends|Suggests" 2>/dev/null', 'ellekit deps')
    c.close()
finally:
    fwd.terminate()
