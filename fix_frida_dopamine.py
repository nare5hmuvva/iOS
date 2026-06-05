import subprocess, sys, time, paramiko, frida

fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', '2222', '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
time.sleep(2)
try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=2222, username='mobile', password='one', timeout=10)

    def run(cmd):
        _, out, err = c.exec_command(cmd)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        if o: print(o)
        if e: print('  stderr:', e[:300])

    # Create ONLY the frida-agent symlink (no frida-helper which doesn't exist)
    run(
        'echo one | /var/jb/usr/bin/sudo -S -p "" sh -c \''
        'PROCURSUS=$(realpath /var/jb); '
        'DOUBLED="${PROCURSUS}${PROCURSUS}"; '
        'mkdir -p "${DOUBLED}/usr/lib/frida-1.0/"; '
        'ln -sf /var/jb/usr/lib/frida-1.0/frida-agent.dylib "${DOUBLED}/usr/lib/frida-1.0/frida-agent.dylib"; '
        'echo "symlink created:"; '
        'ls -la "${DOUBLED}/usr/lib/frida-1.0/"; '
        '\''
    )
    c.close()
finally:
    fwd.terminate()

print('\nTesting frida attach...')
time.sleep(1)

device = frida.get_usb_device(timeout=5)
procs = device.enumerate_processes()
print(f'enumerate OK: {len(procs)} processes')

# Try attaching to progressively more permissive targets
targets = ['MobileNotes', 'MobilePhone', 'MobileSafari', 'backboardd', 'SpringBoard']
for target in targets:
    p = next((x for x in procs if x.name == target), None)
    if not p:
        continue
    print(f'Trying {target} (PID {p.pid})...', end=' ')
    try:
        session = device.attach(p.pid)
        script = session.create_script("rpc.exports = { ping: function(){ return Process.id; } };")
        script.load()
        time.sleep(0.5)
        pid = script.exports.invoke('ping', [])
        print(f'OK (pid={pid})')
        session.detach()
    except Exception as e:
        print(f'FAIL: {type(e).__name__}: {str(e)[:80]}')
