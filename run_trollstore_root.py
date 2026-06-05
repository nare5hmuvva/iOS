"""Run trollstorehelper as root to install DVIA-v2.ipa."""
import subprocess, sys, time, paramiko

USB_PORT   = 2224
MOBILE_PWD = 'one'
HELPER     = '/private/var/containers/Bundle/Application/745A8484-2379-4118-8F2A-5E73986FCAC3/TrollStore.app/trollstorehelper'
IPA        = '/tmp/DVIA-v2.ipa'

fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward',
     str(USB_PORT), '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)

try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=USB_PORT, username='mobile', password=MOBILE_PWD, timeout=12)
    print('SSH OK')

    def run(cmd, label='', timeout=90):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        rc = out.channel.recv_exit_status()
        o  = out.read().decode(errors='replace').strip()
        e  = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        tag = 'OK' if rc == 0 else f'rc={rc}'
        print(f'  [{tag}] {label or cmd[:60]}')
        if txt: print('    ' + txt[:600].replace('\n', '\n    '))
        return o, rc

    # Verify IPA is on device
    run(f'ls -lh {IPA} 2>/dev/null || echo MISSING', 'IPA on device')

    # Run trollstorehelper as root via sudo
    S = f'echo {MOBILE_PWD} | /var/jb/usr/bin/sudo -S -p "" '

    print('\n=== Install DVIA via trollstorehelper (root) ===')
    o, rc = run(S + f'"{HELPER}" install {IPA} 2>&1', 'trollstorehelper install', timeout=90)

    # Check if installed
    installed, _ = run(
        'find /var/containers/Bundle/Application -name "Info.plist" 2>/dev/null '
        '| xargs grep -l "DVIAswiftv2" 2>/dev/null | head -1',
        'DVIA bundle check')

    if installed:
        print(f'\n  DVIA-v2 installed at: {installed}')
        # Run uicache so it appears on home screen
        run('uicache -a 2>/dev/null || /var/jb/usr/bin/uicache -a 2>/dev/null || echo uicache_skipped',
            'uicache refresh')
        print('\n  Done! Open DVIA-v2 from the home screen.')
    else:
        print('\n  Not found via bundle search — trying alternate check...')
        run('ls /var/containers/Bundle/Application/ | tail -5', 'recent app bundles')

        # Maybe it was installed but uicache needs refresh
        run('uicache -a 2>/dev/null || /var/jb/usr/bin/uicache -a 2>/dev/null || echo skip', 'uicache')

        # Try alternate install approaches
        print('\n=== Alternate: use spawn + trollstorehelper ===')
        run(S + f'/var/jb/usr/sbin/spawnroot "{HELPER}" install {IPA} 2>&1',
            'spawnroot install', timeout=90)

    c.close()
finally:
    fwd.terminate()
    print('\nDone.')
