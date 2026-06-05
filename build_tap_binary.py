import subprocess, sys, time, paramiko

HELLO_C = '#include <stdio.h>\nint main(){ printf("hello ok\\n"); return 0; }\n'

TAP_ENT_MINIMAL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>get-task-allow</key><true/>
</dict></plist>"""

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
        if e: print('  err:', e[:400])
        return o

    sftp = c.open_sftp()
    with sftp.open('/tmp/hello.c', 'w') as f:        f.write(HELLO_C)
    with sftp.open('/tmp/tap_min.ent', 'w') as f:    f.write(TAP_ENT_MINIMAL)
    sftp.close()

    # Test 1: unsigned
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c "clang -o /tmp/hello /tmp/hello.c && /tmp/hello; echo exit:$?"', 'unsigned hello')

    # Test 2: ldid -S (no entitlement file)
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c "ldid -S /tmp/hello && /tmp/hello; echo exit:$?"', 'ldid -S no ent')

    # Test 3: minimal entitlement (just get-task-allow)
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c "ldid -S/tmp/tap_min.ent /tmp/hello && /tmp/hello; echo exit:$?"', 'ldid minimal ent')

    # Test 4: check how existing jailbreak binaries run (e.g. opainject is already signed)
    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -e /var/jb/basebin/opainject 2>&1 | head -10', 'opainject entitlements')

    # Test 5: try jbexec if available
    run('which jbexec jbrun 2>/dev/null || echo "no jbexec"', 'jbexec')
    run('ls /var/jb/basebin/ | head -20', 'basebin tools')

    c.close()
finally:
    fwd.terminate()
