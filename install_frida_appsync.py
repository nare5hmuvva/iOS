"""Use device's wget/curl to download and install frida + AppSync."""
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

    # ── 1. frida-server 16.7.19 ──────────────────────────────────────────────
    print('\n=== frida-server 16.7.19 ===')
    # Use GitHub API to get exact asset filenames
    run(S + f'{CURL} -s "https://api.github.com/repos/frida/frida/releases/tags/16.7.19"'
        f' -o /tmp/frida_release.json 2>&1 | tail -2',
        'fetch release JSON', timeout=30)
    assets, _ = run(
        'grep -o \'"browser_download_url":"[^"]*iphoneos-arm64.deb"\' /tmp/frida_release.json'
        ' | grep frida-server | head -3',
        'frida arm64 assets')
    print(f'  assets found: {assets}')

    # Extract URL from JSON
    url_line, _ = run(
        'grep -o \'"browser_download_url":"[^"]*"\' /tmp/frida_release.json'
        ' | grep -i "server" | grep -i "iphoneos-arm64" | head -1'
        ' | sed \'s/"browser_download_url":"//;s/"$//\'',
        'frida url')
    url_line = url_line.strip()
    print(f'  URL: {url_line}')

    if url_line and 'github.com' in url_line:
        run(S + f'{CURL} -L -o /tmp/frida.deb "{url_line}" 2>&1 | tail -3',
            'download frida', timeout=120)
    else:
        # Fallback: try known URL patterns
        for url in [
            'https://github.com/frida/frida/releases/download/16.7.19/frida-server_16.7.19_iphoneos-arm64.deb',
            'https://github.com/frida/frida/releases/download/16.7.19/frida-server-16.7.19-iphoneos-arm64.deb',
            'https://github.com/frida/frida/releases/download/16.7.19/frida_16.7.19_iphoneos-arm64.deb',
        ]:
            o, rc = run(S + f'{CURL} -L -o /tmp/frida.deb --fail "{url}" 2>&1 | tail -2',
                        f'try {url[-50:]}', timeout=120)
            size, _ = run('ls -la /tmp/frida.deb 2>/dev/null | awk \'{print $5}\'', 'size')
            if size.strip().isdigit() and int(size.strip()) > 500_000:
                print(f'    -> downloaded {int(size.strip())//1024}KB')
                break
            run('rm -f /tmp/frida.deb', 'cleanup')

    # Check size and install
    size, _ = run('ls -la /tmp/frida.deb 2>/dev/null | awk \'{print $5}\'', 'frida.deb size')
    if size.strip().isdigit() and int(size.strip()) > 500_000:
        run(S + f'{DPKG} -i --force-all /tmp/frida.deb 2>&1 | tail -8', 'install frida', timeout=60)
    else:
        print('  frida.deb not downloaded properly')

    # ── 2. AppSync Unified ───────────────────────────────────────────────────
    print('\n=== AppSync Unified ===')
    # Procursus sometimes has it
    run(S + f'{APT}-cache search appsync 2>/dev/null', 'apt search appsync')

    # Try alternative AppSync sources
    appsync_urls = [
        # Chariz repo mirror
        'https://repo.chariz.com/api/download/ai.akemi.appsyncunified/latest/iphoneos:arm64',
        # Direct from Akemi CDN alternative
        'https://cydia.akemi.ai/debs/ai.akemi.appsyncunified_116.0_iphoneos-arm64.deb',
    ]

    for url in appsync_urls:
        o, rc = run(S + f'{CURL} -L -o /tmp/appsync.deb --fail "{url}" 2>&1 | tail -2',
                    f'appsync from {url[:50]}', timeout=60)
        size, _ = run('ls -la /tmp/appsync.deb 2>/dev/null | awk \'{print $5}\'', 'size')
        if size.strip().isdigit() and int(size.strip()) > 50_000:
            print(f'    -> {int(size.strip())//1024}KB downloaded')
            break
        run('rm -f /tmp/appsync.deb', 'cleanup')

    size, _ = run('ls -la /tmp/appsync.deb 2>/dev/null | awk \'{print $5}\'', 'appsync.deb size')
    if size.strip().isdigit() and int(size.strip()) > 50_000:
        run(S + f'{DPKG} -i --force-all /tmp/appsync.deb 2>&1 | tail -8',
            'install AppSync', timeout=60)
        run(S + 'launchctl kill SIGKILL system/com.apple.mobile.installd 2>/dev/null; sleep 2',
            'restart installd')
    else:
        print('  AppSync not downloaded — trying procursus install')
        # Maybe procursus has a variant
        run(S + f'{APT}-get install -y --allow-unauthenticated appsync-unified 2>&1 | tail -5',
            'apt install appsync-unified', timeout=60)

    # ── 3. Start frida-server ────────────────────────────────────────────────
    print('\n=== Start frida-server ===')
    run(S + '/var/jb/usr/sbin/frida-server --version 2>/dev/null || echo missing', 'version check')
    run(S + 'killall frida-server 2>/dev/null; '
        'launchctl kill SIGTERM system/re.frida.server 2>/dev/null; '
        'sleep 1; nohup /var/jb/usr/sbin/frida-server &>/tmp/frida.log &',
        'start frida')
    time.sleep(3)
    run('ps aux | grep frida-server | grep -v grep || echo not_running', 'frida status')

    # ── 4. Summary ───────────────────────────────────────────────────────────
    print('\n=== Summary ===')
    run('dpkg -l | grep -E "ellekit|appsync|frida|wget|curl"', 'packages')
    run('ls /var/jb/Library/MobileSubstrate/DynamicLibraries/', 'dylibs')

    c.close()
finally:
    fwd.terminate()
    print('\nDone.')
