"""Diagnose binary execution on Dopamine and test pymobiledevice3 touch injection."""
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
        print(f'--- {label} ---')
        if o: print(o)
        if e: print('  err:', e[:400])
        print()
        return o

    # 1. Get opainject's full entitlements (use cat after extract)
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c "ldid -e /var/jb/basebin/opainject > /tmp/opainject.ent 2>&1; cat /tmp/opainject.ent"',
        'opainject full entitlements')

    # 2. Check Dopamine-specific tools
    run('ls /var/jb/basebin/', 'basebin full list')
    run('ls /var/jb/usr/bin/ | grep -iE "jb|trust|spawn|exec|launch"', 'jb launch tools')

    # 3. Try running hello from /var/jb path (trusted path)
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"cp /tmp/hello /var/jb/usr/bin/hello_test && '
        'ldid -S /var/jb/usr/bin/hello_test && '
        '/var/jb/usr/bin/hello_test; echo exit:$?"',
        'hello from /var/jb/usr/bin/')

    # 4. Try launchctl spawn (provides full bootstrap)
    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/launchctl spawn / /var/jb/usr/bin/hello_test 2>&1; echo exit:$?',
        'launchctl spawn hello')

    # 5. Check amfid/kernel deny messages
    run('echo one | /var/jb/usr/bin/sudo -S -p "" dmesg 2>/dev/null | grep -iE "amfid|deny|kill|sigkill" | tail -15',
        'dmesg amfid/kill messages')

    # 6. Check if we can use jailbreakd to trust the binary
    run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/basebin/jailbreakd --help 2>&1 | head -10',
        'jailbreakd help')

    # 7. Try signing with platform-application entitlement (Dopamine's typical bypass)
    PLATFORM_ENT = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>platform-application</key><true/>
    <key>get-task-allow</key><true/>
    <key>com.apple.private.security.no-sandbox</key><true/>
    <key>com.apple.private.skip-library-validation</key><true/>
</dict></plist>'''

    sftp = c.open_sftp()
    with sftp.open('/tmp/platform.ent', 'w') as f:
        f.write(PLATFORM_ENT)
    sftp.close()

    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"cp /tmp/hello /tmp/hello_plat && '
        'ldid -S/tmp/platform.ent /tmp/hello_plat && '
        '/tmp/hello_plat; echo exit:$?"',
        'hello with platform-application ent')

    # 8. Check if there is a trust cache tool
    run('ls /var/jb/usr/bin/ | head -40', 'full jb usr bin')

    # 9. Check if WDA or simulated tap tools exist
    run('ls /var/mobile/Containers/Bundle/ 2>/dev/null | grep -i wda || echo "no wda"', 'WDA check')
    run('which activator 2>/dev/null || echo "no activator"', 'activator')

    c.close()
finally:
    fwd.terminate()
