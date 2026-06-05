"""Install frida (already at /tmp/frida.deb) + find working AppSync source."""
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

    def run(cmd, label='', timeout=180):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        rc = out.channel.recv_exit_status()
        o  = out.read().decode(errors='replace').strip()
        e  = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        tag = 'OK' if rc == 0 else f'rc={rc}'
        print(f'  [{tag}] {label or cmd[:60]}')
        if txt: print('    ' + txt[:500].replace('\n', '\n    '))
        return o, rc

    # ── 1. Install frida (already downloaded) ────────────────────────────────
    print('\n=== Install frida-server 16.7.19 ===')
    size, _ = run(S + 'ls -la /tmp/frida.deb 2>/dev/null', 'frida.deb check')
    if '/tmp/frida.deb' in size:
        run(S + f'{DPKG} -i --force-all /tmp/frida.deb 2>&1', 'install frida', timeout=60)
    else:
        # Re-download
        run(S + f'{CURL} -L -o /tmp/frida.deb '
            '"https://github.com/frida/frida/releases/download/16.7.19/frida_16.7.19_iphoneos-arm64.deb"'
            ' 2>&1 | tail -2', 'download frida', timeout=120)
        run(S + f'{DPKG} -i --force-all /tmp/frida.deb 2>&1', 'install frida', timeout=60)

    # Verify and start
    run(S + '/var/jb/usr/sbin/frida-server --version 2>/dev/null || echo MISSING', 'frida version')
    run(S + 'killall frida-server 2>/dev/null; sleep 1; '
        'nohup /var/jb/usr/sbin/frida-server &>/tmp/frida.log &',
        'start frida')
    time.sleep(3)
    run('ps aux | grep frida-server | grep -v grep || echo not_running', 'frida pid')

    # ── 2. AppSync Unified ───────────────────────────────────────────────────
    print('\n=== AppSync Unified ===')

    # Try Procursus (has appsync-unified or appinst)
    run(S + f'{APT} update 2>&1 | grep -v "^W:\\|^E:\\|^Reading\\|^Get" | head -5',
        'apt update', timeout=60)

    run(S + f'apt-cache search appsync appinst 2>/dev/null', 'search packages')

    # Try installing from Procursus
    run(S + f'{APT} install -y --allow-unauthenticated appsync-unified 2>&1 | tail -5',
        'apt install appsync-unified', timeout=90)

    # Try appinst as alternative (Procursus has this)
    run(S + f'{APT} install -y --allow-unauthenticated appinst 2>&1 | tail -5',
        'apt install appinst', timeout=90)

    # Try direct download from known working URLs
    appsync_sources = [
        # Procursus mirror
        'https://apt.procurs.us/pool/main/a/appsync-unified/appsync-unified_116.0_iphoneos-arm64.deb',
        # Try older version
        'https://cydia.akemi.ai/debs/ai.akemi.appsyncunified_116.0_iphoneos-arm64.deb',
    ]
    for url in appsync_sources:
        o, rc = run(S + f'{CURL} -L -m 15 -o /tmp/appsync.deb --fail "{url}" 2>&1 | tail -2',
                    f'try {url[-40:]}', timeout=30)
        size_o, _ = run(S + 'ls -la /tmp/appsync.deb 2>/dev/null | cut -d" " -f5-', 'size')
        # Check if file is big enough
        try:
            sz_parts = size_o.strip().split()
            sz = int(sz_parts[0]) if sz_parts else 0
        except Exception:
            sz = 0
        if sz > 50_000:
            print(f'  -> downloaded {sz//1024}KB')
            run(S + f'{DPKG} -i --force-all /tmp/appsync.deb 2>&1 | tail -8',
                'install AppSync', timeout=60)
            break
        run(S + 'rm -f /tmp/appsync.deb', 'cleanup')

    # Check result
    appsync_ok, _ = run(
        S + 'ls /var/jb/Library/MobileSubstrate/DynamicLibraries/AppSync* 2>/dev/null || echo MISSING',
        'AppSync dylib')

    if 'MISSING' in appsync_ok:
        print('\n  NOTE: AppSync not installed via apt/download.')
        print('  Trying alternative: install via Sileo/Zebra on device')
        print('  OR we can use pymobiledevice3 install_developer_app which bypasses signing')

    # ── 3. Restart installd with AppSync ────────────────────────────────────
    run(S + 'launchctl kill SIGKILL system/com.apple.mobile.installd 2>/dev/null; '
        'sleep 2; echo restarted', 'restart installd')

    # ── 4. Summary ───────────────────────────────────────────────────────────
    print('\n=== Final Status ===')
    run('dpkg -l | grep -E "ellekit|appsync|frida|appinst|wget|curl"', 'packages')
    run('ls /var/jb/Library/MobileSubstrate/DynamicLibraries/', 'dylibs')
    run('ps aux | grep frida-server | grep -v grep || echo frida_not_running', 'frida')
    run(S + 'which appinst /var/jb/usr/bin/appinst 2>/dev/null || echo no_appinst', 'appinst path')

    c.close()
finally:
    fwd.terminate()
    print('\nDone.')
