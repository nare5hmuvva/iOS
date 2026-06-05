"""Get AppSync from GitHub releases using device curl, then install."""
import subprocess, sys, time, paramiko, json

USB_PORT   = 2224
MOBILE_PWD = 'one'
CURL       = '/var/jb/usr/bin/curl'
DPKG       = '/var/jb/usr/bin/dpkg'

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

    # ── 1. Get AppSync release info from GitHub API ──────────────────────────
    print('\n=== GitHub AppSync releases ===')
    run(f'{CURL} -sL "https://api.github.com/repos/akemin-dayo/AppSync/releases" '
        f'-o /tmp/appsync_releases.json --max-time 15 2>&1 | tail -1',
        'fetch releases JSON')

    assets_raw, _ = run(
        'cat /tmp/appsync_releases.json 2>/dev/null | '
        'grep -o \'"browser_download_url":"[^"]*\\.deb"\' | head -20',
        'deb assets')
    print(f'  All deb assets:\n    {assets_raw.replace(chr(10), chr(10)+"    ")}')

    # Find arm64 deb
    url_line, _ = run(
        'cat /tmp/appsync_releases.json 2>/dev/null | '
        'grep -o \'"browser_download_url":"[^"]*\\.deb"\' | '
        'grep -i "arm64\\|iphoneos" | head -1 | '
        'sed \'s/"browser_download_url":"//;s/"$//\'',
        'arm64 deb URL')
    url_line = url_line.strip()
    print(f'  URL: {url_line}')

    if 'github.com' in url_line:
        run(f'{CURL} -L -o /tmp/appsync.deb "{url_line}" --max-time 60 2>&1 | tail -2',
            'download AppSync', timeout=90)
    else:
        # Try known direct URL patterns for AppSync
        for url in [
            'https://github.com/akemin-dayo/AppSync/releases/download/116.0/ai.akemi.appsyncunified_116.0_iphoneos-arm64.deb',
            'https://github.com/akemin-dayo/AppSync/releases/latest/download/ai.akemi.appsyncunified_iphoneos-arm64.deb',
            'https://github.com/akemin-dayo/AppSync/releases/latest/download/AppSyncUnified_iphoneos-arm64.deb',
        ]:
            o, rc = run(f'{CURL} -L -o /tmp/appsync.deb --fail --max-time 20 "{url}" 2>&1 | tail -2',
                        f'{url[-50:]}', timeout=30)
            sz_out, _ = run('ls -la /tmp/appsync.deb 2>/dev/null', 'size')
            try:
                sz = int(sz_out.split()[4])
            except Exception:
                sz = 0
            if sz > 30_000:
                print(f'    -> {sz//1024}KB downloaded')
                break
            run('rm -f /tmp/appsync.deb 2>/dev/null', 'cleanup')

    # ── 2. Check download and install ────────────────────────────────────────
    size_out, _ = run('ls -la /tmp/appsync.deb 2>/dev/null || echo MISSING', 'appsync.deb')
    try:
        sz = int(size_out.split()[4])
    except Exception:
        sz = 0

    if sz > 30_000:
        print(f'\n  Downloaded {sz//1024}KB — installing...')
        run(S + f'{DPKG} -i --force-all /tmp/appsync.deb 2>&1', 'install AppSync', timeout=60)

        # Verify dylib presence
        run(S + 'ls /var/jb/Library/MobileSubstrate/DynamicLibraries/ | grep -i appsync || echo MISSING',
            'AppSync dylib')

        # Kill installd so it reloads with AppSync hooked
        run(S + 'launchctl kill SIGKILL system/com.apple.mobile.installd 2>/dev/null; '
            'sleep 2; echo installd_restarted', 'restart installd')
        print('\n  AppSync installed! Wait 5 seconds then retry the IPA install.')
    else:
        print('\n  Could not download AppSync from GitHub.')
        print('  BEST OPTION: Install manually via Sileo on the device:')
        print('    1. Open Sileo on iPhone')
        print('    2. Sources -> + -> https://cydia.akemi.ai/')
        print('    3. Install "AppSync Unified"')
        print()
        print('  OR sign the IPA with a free Apple ID using Sideloadly:')
        print('    https://sideloadly.io')

    c.close()
finally:
    fwd.terminate()
