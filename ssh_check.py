"""Start a pymobiledevice3 USB->TCP forwarder, then SSH in to check frida."""
import asyncio
import subprocess
import sys
import time
import threading

# Start the port forwarder in a background thread
fwd_proc = None

def start_forwarder():
    global fwd_proc
    fwd_proc = subprocess.Popen(
        [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', '2222', '22'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    fwd_proc.wait()

t = threading.Thread(target=start_forwarder, daemon=True)
t.start()
time.sleep(3)
print('Forwarder started, trying SSH on localhost:2222...')

# SSH in to check for frida
cmd = [
    'ssh',
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'ConnectTimeout=5',
    '-o', 'PasswordAuthentication=no',
    '-o', 'PubkeyAuthentication=no',
    '-p', '2222',
    'mobile@127.0.0.1',
    'echo connected'
]
try:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    print('SSH stdout:', r.stdout)
    print('SSH stderr:', r.stderr)
    print('returncode:', r.returncode)
except Exception as e:
    print('SSH error:', e)

# Try with password via sshpass
print()
print('Trying sshpass...')
cmd2 = ['sshpass', '-p', 'one',
        'ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=5',
        '-p', '2222', 'mobile@127.0.0.1',
        'echo "connected"; find /var/jb /usr -name "frida-server" 2>/dev/null; ps aux 2>/dev/null | grep frida | grep -v grep']
try:
    r = subprocess.run(cmd2, capture_output=True, text=True, timeout=10)
    print('stdout:', r.stdout)
    print('stderr:', r.stderr[:300])
except FileNotFoundError:
    print('sshpass not found')
except Exception as e:
    print('sshpass error:', e)

# Try paramiko
print()
print('Trying paramiko SSH...')
try:
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('127.0.0.1', port=2222, username='mobile', password='one', timeout=8)
    # Use sudo with password one to run as root (Dopamine rootless)
    cmd = (
        'echo one | /var/jb/usr/bin/sudo -S -p "" sh -c \''
        'echo "=== SSH as root ==="; '
        'find /var/jb /usr /bin /sbin /Library -name "frida-server" 2>/dev/null; '
        'echo "---dpkg---"; /var/jb/usr/bin/dpkg -l 2>/dev/null | grep -i frida; '
        'echo "---ps---"; ps aux 2>/dev/null | grep frida | grep -v grep; '
        'echo "---launchdaemons---"; ls /var/jb/Library/LaunchDaemons/ 2>/dev/null | grep -i frida'
        '\''
    )
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode()
    err = stderr.read().decode()
    client.close()
    print('OUTPUT:')
    print(out)
    if err:
        print('STDERR:', err[:200])
except Exception as e:
    print(f'paramiko: {type(e).__name__}: {e}')

if fwd_proc:
    fwd_proc.terminate()
