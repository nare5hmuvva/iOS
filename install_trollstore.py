"""Install TrollStore 2 via SSH on Dopamine-jailbroken device.
TrollStore permanently installs unsigned IPAs — replaces AppSync entirely.
"""
import subprocess, sys, time, paramiko

USB_PORT   = 2224
MOBILE_PWD = 'one'
CURL       = '/var/jb/usr/bin/curl'
DPKG       = '/var/jb/usr/bin/dpkg'
APT        = '/var/jb/usr/bin/apt-get'

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
    S = f'echo {MOBILE_PWD} | /var/jb/usr/bin/sudo -S -p "" '

    def run(cmd, label='', timeout=120):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        rc = out.channel.recv_exit_status()
        o  = out.read().decode(errors='replace').strip()
        e  = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        tag = 'OK' if rc == 0 else f'rc={rc}'
        print(f'  [{tag}] {label or cmd[:60]}')
        if txt: print('    ' + txt[:600].replace('\n', '\n    '))
        return o, rc

    # ── Check if TrollStore is already installed ──────────────────────────────
    print('\n=== TrollStore check ===')
    run('ls /var/containers/Bundle/Application/*/TrollStore.app/trollstorehelper 2>/dev/null || echo not_installed',
        'TrollStore installed?')
    run('which trollstorehelper /var/jb/usr/bin/trollstorehelper 2>/dev/null || echo no_helper',
        'trollstorehelper binary')

    # ── Check Havoc for TrollStore packages ───────────────────────────────────
    print('\n=== Search repos for TrollStore ===')
    run(S + 'apt-cache search trollstore 2>/dev/null', 'apt search trollstore')
    run(S + 'apt-cache search troll 2>/dev/null | head -10', 'apt search troll')

    # ── Download TrollStore 2 installer directly from GitHub ─────────────────
    print('\n=== Download TrollStore 2 installer ===')
    # TrollInstallerX for Dopamine rootless
    installer_urls = [
        'https://github.com/opa334/TrollInstallerX/releases/latest/download/TrollInstallerX.ipa',
        'https://github.com/opa334/TrollStore/releases/latest/download/TrollInstaller.tar',
    ]

    # Get latest release info
    run(f'{CURL} -sL "https://api.github.com/repos/opa334/TrollInstallerX/releases/latest" '
        f'-o /tmp/ts_release.json --max-time 15', 'fetch TrollInstallerX release', timeout=30)

    ts_url, _ = run(
        'cat /tmp/ts_release.json 2>/dev/null | '
        'grep -o \'"browser_download_url":"[^"]*\\.ipa"\' | head -1 | '
        'sed \'s/"browser_download_url":"//;s/"$//\'',
        'TrollInstallerX IPA URL')
    ts_url = ts_url.strip()
    print(f'  TrollInstallerX URL: {ts_url}')

    # Also try TrollStore Helper (ldid-signable helper binary)
    run(f'{CURL} -sL "https://api.github.com/repos/opa334/TrollStore/releases/latest" '
        f'-o /tmp/ts2_release.json --max-time 15', 'fetch TrollStore release', timeout=30)

    helper_url, _ = run(
        'cat /tmp/ts2_release.json 2>/dev/null | '
        'grep -o \'"browser_download_url":"[^"]*\\.tar"\' | head -1 | '
        'sed \'s/"browser_download_url":"//;s/"$//\'',
        'TrollStore.tar URL')
    helper_url = helper_url.strip()
    print(f'  TrollStore tar URL: {helper_url}')

    # ── Install via the jailbreak-native method ───────────────────────────────
    # On Dopamine, TrollHelper can be installed by placing it at a known path
    # and registering it. Then TrollHelper.app installs TrollStore from Tips.
    print('\n=== Install TrollStore via Dopamine bootstrap ===')

    if helper_url and 'github.com' in helper_url:
        run(S + f'{CURL} -L -o /tmp/TrollStore.tar "{helper_url}" --max-time 60 2>&1 | tail -2',
            'download TrollStore.tar', timeout=90)
        size_o, _ = run(S + 'ls -la /tmp/TrollStore.tar 2>/dev/null || echo MISSING', 'size')
        try:
            sz = int(size_o.split()[4])
        except Exception:
            sz = 0

        if sz > 100_000:
            print(f'  Downloaded {sz//1024}KB')
            # Extract
            run(S + 'tar -xf /tmp/TrollStore.tar -C /tmp/ 2>&1 | head -5', 'extract', timeout=30)
            run(S + 'ls /tmp/TrollHelper* /tmp/trollstorehelper* /tmp/TrollStore* 2>/dev/null | head -10',
                'extracted files')
            # The TrollHelper binary installs TrollStore
            run(S + 'ls -la /tmp/trollstorehelper 2>/dev/null || ls -la /tmp/TrollHelper 2>/dev/null',
                'helper binary')
            # Sign and run helper
            run(S + '/var/jb/usr/bin/ldid -S /tmp/trollstorehelper 2>/dev/null; '
                'chmod +x /tmp/trollstorehelper; '
                '/tmp/trollstorehelper install 2>&1 | head -10',
                'run TrollStore helper install', timeout=30)
        else:
            print('  TrollStore.tar not downloaded')
    else:
        print('  Could not get TrollStore download URL from GitHub')

    # ── Alternative: use TrollStore Helper deb from Havoc ────────────────────
    print('\n=== Try Havoc TrollStore helper deb ===')
    run(S + f'apt-cache show com.opa334.trollstorehelper 2>/dev/null | head -5', 'havoc trollstore')
    run(S + f'{APT} install -y --allow-unauthenticated com.opa334.trollstorehelper 2>&1 | tail -5',
        'install trollstorehelper', timeout=60)
    run(S + 'which trollstorehelper /var/jb/usr/bin/trollstorehelper 2>/dev/null || echo not_found',
        'trollstorehelper path after install')

    c.close()
finally:
    fwd.terminate()
    print('\nDone.')
