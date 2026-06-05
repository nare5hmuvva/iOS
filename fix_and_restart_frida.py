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

    def run(cmd, label=''):
        _, out, err = c.exec_command(cmd)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        if label: print(f'--- {label} ---')
        if o: print(o)
        if e: print(f'  stderr: {e[:200]}')

    run('ps aux | grep frida | grep -v grep', 'frida processes')

    # Remove everything we created in the doubled path â€” it may have broken things
    run(
        'echo one | /var/jb/usr/bin/sudo -S -p "" sh -c \''
        'PROCURSUS=$(realpath /var/jb); '
        'DOUBLED="${PROCURSUS}${PROCURSUS}"; '
        'rm -rf "${DOUBLED}" 2>/dev/null; '
        'echo "cleaned doubled path"; '
        '\'',
        'cleanup doubled path'
    )

    # Check what is actually in frida-1.0
    run('ls -la /var/jb/usr/lib/frida-1.0/', 'frida-1.0 contents')
    run('find /var/jb/usr/lib/ -name "frida*" 2>/dev/null', 'all frida libs')
    run('find /var/jb/usr/ -name "frida*" 2>/dev/null', 'all frida binaries')

    # Kill all frida, restart cleanly via launchdaemon
    run(
        'echo one | /var/jb/usr/bin/sudo -S -p "" sh -c \''
        'killall -9 frida-server 2>/dev/null; '
        'sleep 1; '
        '/var/jb/bin/launchctl unload /var/jb/Library/LaunchDaemons/re.frida.server.plist 2>/dev/null; '
        'sleep 1; '
        '/var/jb/bin/launchctl load /var/jb/Library/LaunchDaemons/re.frida.server.plist 2>/dev/null; '
        'sleep 2; '
        'ps aux | grep frida-server | grep -v grep; '
        '\'',
        'restart via launchctl'
    )

    c.close()
finally:
    fwd.terminate()
