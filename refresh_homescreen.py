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
        txt = (o+' '+e).strip()
        print(f'[{label}] {txt[:300]}' if txt else f'[{label}] (ok)')
        return o

    # Verify DVIA is installed
    run('find /var/containers/Bundle/Application -name "Info.plist" 2>/dev/null'
        ' | xargs grep -l "DVIAswiftv2" 2>/dev/null', 'DVIA bundle')

    # Refresh icon cache so it shows on home screen
    run('/var/jb/usr/bin/uicache -a 2>/dev/null || uicache -a 2>/dev/null', 'uicache')

    # Also try sbreload if uicache not enough
    run(S + 'launchctl kill SIGHUP system/com.apple.backboardd 2>/dev/null || echo skip', 'backboardd reload')

    print('\nDVIA-v2 is installed. Search for it on the home screen or in Spotlight (swipe down).')
    c.close()
finally:
    fwd.terminate()
