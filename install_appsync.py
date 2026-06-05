"""
Connect to the iPhone via USB tunnel and install AppSync Unified .deb directly.
Run this script, then enter the .deb URL when prompted (or pass it as argv[1]).

AppSync Unified deb URL (check https://github.com/akemin-dayo/AppSync for latest):
  e.g. https://cydia.akemi.ai/debs/ai.akemi.appsyncunified_<version>_iphoneos-arm64.deb
"""
import subprocess, sys, threading, time, paramiko

DEB_URL = sys.argv[1] if len(sys.argv) > 1 else input("Enter AppSync .deb URL: ").strip()

# Start USB port forwarder (port 22 -> localhost:2222)
fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', '2222', '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
time.sleep(2)

try:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('127.0.0.1', port=2222, username='mobile', password='one', timeout=10)
    print('[+] SSH connected')

    cmds = [
        f'echo one | /var/jb/usr/bin/sudo -S -p "" curl -Lo /tmp/appsync.deb "{DEB_URL}"',
        'echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/dpkg -i /tmp/appsync.deb',
        'echo one | /var/jb/usr/bin/sudo -S -p "" uicache -a',
    ]
    for cmd in cmds:
        print(f'\n$ {cmd.split("sudo")[1][:60].strip()}...')
        _, out, err = client.exec_command(cmd)
        print(out.read().decode())
        e = err.read().decode()
        if e: print('stderr:', e[:300])

    client.close()
    print('\n[+] Done â€” try installing the IPA again from the dashboard.')
finally:
    fwd.terminate()
