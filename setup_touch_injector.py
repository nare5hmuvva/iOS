"""Install Python3 on device, deploy touch_inject.py, and test a tap."""
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
        if label: print(f'--- {label} ---')
        if o: print(o)
        if e: print('  err:', e[:300])

    # Install python3
    print('Installing python3...')
    run(
        'echo one | /var/jb/usr/bin/sudo -S -p "" apt-get install -y python3 2>&1 | '
        'grep -E "Setting up|already|Err|error" || true',
        'apt-get python3', timeout=120
    )
    run('which python3 2>/dev/null || echo "python3 still not found"', 'python3 check')

    # Upload touch_inject.py to the device
    sftp = c.open_sftp()
    sftp.put('touch_inject.py', '/var/mobile/touch_inject.py')
    sftp.close()
    print('Uploaded touch_inject.py to /var/mobile/touch_inject.py')

    # Test tap at screen center
    print()
    run(
        'echo one | /var/jb/usr/bin/sudo -S -p "" python3 /var/mobile/touch_inject.py tap 187 333 2>&1',
        'test tap (187, 333)'
    )

    c.close()
finally:
    fwd.terminate()
