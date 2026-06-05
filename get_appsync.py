"""Find and install AppSync from accessible repos + install DVIA-v2."""
import subprocess, sys, time, paramiko, io

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

    def run(cmd, label='', timeout=60):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        rc = out.channel.recv_exit_status()
        o  = out.read().decode(errors='replace').strip()
        e  = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        tag = 'OK' if rc == 0 else f'rc={rc}'
        print(f'  [{tag}] {label or cmd[:60]}')
        if txt: print('    ' + txt[:600].replace('\n', '\n    '))
        return o, rc

    # ── Search all cached repos for AppSync ──────────────────────────────────
    print('\n=== Search apt cache for appsync/signing bypass ===')
    run(S + 'apt-cache search sign install bypass 2>/dev/null | grep -i -E "appsync|sign|install" | head -20',
        'search')
    run(S + 'apt-cache search appsync 2>/dev/null | head -10', 'appsync search')
    run(S + f'apt-cache show ai.akemi.appsyncunified 2>/dev/null | head -5', 'appsync show')

    # Chariz repo - search using API
    print('\n=== Chariz repo API ===')
    run(S + f'{CURL} -s "https://repo.chariz.com/Packages.bz2" -o /tmp/chariz_pkgs.bz2 2>&1 | tail -1',
        'fetch Chariz Packages', timeout=30)
    run(S + 'bunzip2 -c /tmp/chariz_pkgs.bz2 2>/dev/null | grep -A5 -i "appsync" | head -30',
        'appsync in chariz')

    # Procursus - full package list
    run(S + f'{APT}-cache search "" 2>/dev/null | grep -i -E "appsync|unsigned|codesign" | head -10',
        'all repos appsync')

    # ── Try alternate AppSync download URLs ──────────────────────────────────
    print('\n=== Try AppSync download URLs ===')
    urls = [
        # Chariz direct download API
        'https://repo.chariz.com/api/download/ai.akemi.appsyncunified/latest',
        # GitHub release
        'https://github.com/akemin-dayo/AppSync/releases/latest/download/appsyncunified_iphoneos-arm64.deb',
        # Havoc repo API
        'https://havoc.app/api/download/ai.akemi.appsyncunified',
        # Procursus
        'https://apt.procurs.us/pool/main/a/ai.akemi.appsyncunified/ai.akemi.appsyncunified_116.0_iphoneos-arm64.deb',
    ]
    downloaded = False
    for url in urls:
        o, rc = run(S + f'{CURL} -L -m 20 -o /tmp/appsync.deb --fail "{url}" 2>&1 | tail -2',
                    f'{url[:60]}', timeout=30)
        # Check file size
        sz_o, _ = run(S + 'ls -la /tmp/appsync.deb 2>/dev/null', 'size check')
        try:
            sz = int(sz_o.split()[4]) if sz_o else 0
        except Exception:
            sz = 0
        if sz > 50_000:
            print(f'    -> {sz//1024}KB downloaded!')
            run(S + f'{DPKG} -i --force-all /tmp/appsync.deb 2>&1 | tail -8',
                'install AppSync', timeout=60)
            downloaded = True
            break
        run(S + 'rm -f /tmp/appsync.deb 2>/dev/null', 'cleanup')

    if not downloaded:
        print('\n  AppSync not downloadable from any source right now.')
        print('  Using pymobiledevice3 developer install as fallback.')

    # ── Check AppSync result ─────────────────────────────────────────────────
    run(S + 'ls /var/jb/Library/MobileSubstrate/DynamicLibraries/AppSync* 2>/dev/null || echo MISSING',
        'AppSync dylib')

    # ── Try pymobiledevice3 install (bypasses signing for dev mode) ──────────
    print('\n=== Check DVIA IPA path on Windows ===')
    # DVIA IPA should be somewhere
    import os
    base = r'c:\Users\muvva\Desktop\iOS_Project'
    for root_d, dirs, files in os.walk(base):
        for f in files:
            if 'dvia' in f.lower() or 'DVIA' in f:
                print(f'  Found IPA: {os.path.join(root_d, f)}')

    c.close()
finally:
    fwd.terminate()
    print('\nDone.')
