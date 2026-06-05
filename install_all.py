"""Install AppSync Unified, frida-server 16.7.19, fix root, and install DVIA.
Uses direct .deb downloads — no repo config needed.
"""
import subprocess, sys, time, paramiko, io
from pathlib import Path

USB_PORT   = 2224
MOBILE_PWD = 'one'
ROOT_PWD   = 'alpine'

fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward',
     str(USB_PORT), '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)

try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=USB_PORT, username='mobile',
              password=MOBILE_PWD, timeout=12)
    print('SSH OK')

    def run(cmd, label='', timeout=180):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        rc = out.channel.recv_exit_status()
        o  = out.read().decode(errors='replace').strip()
        e  = err.read().decode(errors='replace').strip()
        tag = 'OK' if rc == 0 else f'rc={rc}'
        txt = (o + ' ' + e).strip()
        print(f'  [{tag}] {label or cmd[:50]}')
        if txt: print('    ' + txt[:500].replace('\n', '\n    '))
        return o

    S = f'echo "{MOBILE_PWD}" | /var/jb/usr/bin/sudo -S -p "" '

    # ── 1. Locate tools ──────────────────────────────────────────────────────
    print('\n=== Locating tools ===')
    run('which curl wget dpkg apt-get 2>/dev/null || echo checking jb paths', 'system tools')
    curl_path = run('ls /var/jb/usr/bin/curl /usr/bin/curl 2>/dev/null | head -1', 'curl path').strip()
    wget_path = run('ls /var/jb/usr/bin/wget /usr/bin/wget 2>/dev/null | head -1', 'wget path').strip()
    dl_tool = curl_path or wget_path
    if curl_path:
        dl_cmd = f'{curl_path} -L -o'
    elif wget_path:
        dl_cmd = f'{wget_path} -O'
    else:
        dl_cmd = None
    print(f'  download tool: {dl_cmd or "NONE FOUND"}')

    run(f'ls /var/jb/usr/bin/dpkg /usr/bin/dpkg 2>/dev/null', 'dpkg path')

    # ── 2. Fix root password via chpasswd ────────────────────────────────────
    print('\n=== Fix root password ===')
    run(S + f'/var/jb/usr/bin/sh -c "echo \'root:{ROOT_PWD}\' | chpasswd 2>&1 || '
        f'printf \'{ROOT_PWD}\\n{ROOT_PWD}\\n\' | passwd root 2>&1"',
        f'set root pwd={ROOT_PWD}')

    # Fix sshd_config — find it first
    sshd_cfg = run('find /var/jb /etc /usr -name sshd_config 2>/dev/null | head -1',
                   'find sshd_config').strip()
    print(f'  sshd_config: {sshd_cfg or "not found"}')
    if sshd_cfg:
        run(S + f'/var/jb/usr/bin/sh -c \''
            f'sed -i "s/#*PermitRootLogin.*/PermitRootLogin yes/" {sshd_cfg}; '
            f'sed -i "s/#*PasswordAuthentication.*/PasswordAuthentication yes/" {sshd_cfg}; '
            f'echo done\'', 'enable root SSH')
        run(S + 'launchctl kickstart -k system/com.openssh.sshd 2>&1 || echo skip',
            'reload sshd')

    # ── 3. Install AppSync Unified (direct deb) ──────────────────────────────
    print('\n=== Install AppSync Unified ===')
    run(S + 'ls /var/jb/Library/MobileSubstrate/DynamicLibraries/AppSync* 2>/dev/null || echo not_installed',
        'AppSync current state')

    if dl_cmd:
        # AppSync 116.0 for Dopamine/rootless from Procursus
        appsync_url = 'https://cydia.akemi.ai/debs/ai.akemi.appsyncunified_116.0_iphoneos-arm64.deb'
        run(S + f'{dl_cmd} /tmp/appsync.deb "{appsync_url}" 2>&1 | tail -3',
            'download AppSync', timeout=60)
        run(S + 'dpkg -i --force-all /tmp/appsync.deb 2>&1 | tail -8',
            'install AppSync', timeout=60)

        # Verify
        run(S + 'ls /var/jb/Library/MobileSubstrate/DynamicLibraries/AppSync* 2>/dev/null || echo STILL_MISSING',
            'AppSync verify')

        # Restart installd to pick up AppSync hook
        run(S + 'launchctl kill SIGKILL system/com.apple.mobile.installd 2>/dev/null; '
            'sleep 2; echo installd_restarted', 'restart installd')
    else:
        print('  SKIP: no download tool found')

    # ── 4. Install frida-server 16.7.19 ─────────────────────────────────────
    print('\n=== Install frida-server 16.7.19 ===')

    frida_ver = run('/var/jb/usr/sbin/frida-server --version 2>/dev/null || '
                    'frida-server --version 2>/dev/null || echo missing',
                    'frida-server current').strip()
    print(f'  current: {frida_ver}')

    if '16.7.19' not in frida_ver:
        if dl_cmd:
            # Try arm64 first, then arm (iPhone 7 is arm64)
            frida_url = 'https://github.com/frida/frida/releases/download/16.7.19/frida-server_16.7.19_iphoneos-arm64.deb'
            run(S + f'{dl_cmd} /tmp/frida.deb "{frida_url}" 2>&1 | tail -3',
                'download frida 16.7.19', timeout=120)
            run(S + 'dpkg -i --force-all /tmp/frida.deb 2>&1 | tail -5',
                'install frida deb', timeout=60)
        else:
            print('  SKIP: no download tool')

    # Kill old frida, start fresh
    run(S + 'killall frida-server 2>/dev/null; '
        'launchctl kill SIGTERM system/re.frida.server 2>/dev/null; '
        'sleep 1; echo killed', 'kill old frida')
    run(S + '/var/jb/usr/sbin/frida-server -D 2>/dev/null & '
        'sleep 2 && echo started', 'start frida-server', timeout=10)
    time.sleep(3)
    frida_running = run('ps aux | grep frida-server | grep -v grep', 'frida running')

    # ── 5. Check DVIA state ──────────────────────────────────────────────────
    print('\n=== DVIA-v2 check ===')
    BUNDLE = 'com.highaltitudehacks.DVIAswiftv2'
    dvia_path = run(
        f'find /var/containers/Bundle/Application -name "Info.plist" 2>/dev/null'
        f' | xargs grep -l "{BUNDLE}" 2>/dev/null | head -1 | xargs dirname 2>/dev/null',
        'DVIA install path').strip()
    print(f'  app path: {dvia_path or "NOT INSTALLED"}')

    if dvia_path:
        # Get binary
        binary_name = run(
            f'plutil -key CFBundleExecutable "{dvia_path}/Info.plist" 2>/dev/null || '
            f'grep -A1 CFBundleExecutable "{dvia_path}/Info.plist" | grep string | '
            f'sed "s/.*<string>\\(.*\\)<\\/string>.*/\\1/"',
            'binary name').strip()
        if binary_name:
            bp = f'{dvia_path}/{binary_name}'
            run(f'file "{bp}" 2>/dev/null || xxd "{bp}" | head -2', 'binary arch')
            run(f'ls -la "{bp}"', 'binary size')

    # Check crash logs
    crashes = run(
        'ls -t /private/var/mobile/Library/Logs/CrashReporter/ 2>/dev/null'
        ' | grep -i dvia | head -3', 'crash logs')
    if crashes:
        first = crashes.strip().splitlines()[0]
        run(f'head -80 "/private/var/mobile/Library/Logs/CrashReporter/{first}"',
            'latest crash')

    # ── 6. Summary ───────────────────────────────────────────────────────────
    print('\n=== Summary ===')
    run('dpkg -l | grep -E "ellekit|appsync|frida" 2>/dev/null', 'installed pkgs')
    run('ls /var/jb/Library/MobileSubstrate/DynamicLibraries/ 2>/dev/null', 'dylibs')
    run('ps aux | grep frida-server | grep -v grep || echo frida_not_running',
        'frida status')

    c.close()

finally:
    fwd.terminate()
    print('\nDone.')
