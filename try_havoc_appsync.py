"""Try Havoc and BigBoss repos for AppSync or equivalent."""
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

    def run(cmd, label='', timeout=90):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        rc = out.channel.recv_exit_status()
        o  = out.read().decode(errors='replace').strip()
        e  = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        tag = 'OK' if rc == 0 else f'rc={rc}'
        print(f'  [{tag}] {label or cmd[:60]}')
        if txt: print('    ' + txt[:500].replace('\n', '\n    '))
        return o, rc

    # ── Search all available repos ───────────────────────────────────────────
    print('\n=== All available packages matching sign/install ===')
    run(S + f'apt-cache search "" 2>/dev/null | grep -iE "appsync|codesign|install.*ipa|bypass.*sign" | head -20',
        'full search')

    # Dump all package names from Havoc/Chariz
    run(S + f'{APT}-cache pkgnames 2>/dev/null | grep -iE "appsync|appinst|codesign" | head -20',
        'pkgnames search')

    # Try Havoc API directly
    print('\n=== Havoc repo search ===')
    run(f'{CURL} -sL "https://havoc.app/depiction/ai.akemi.appsyncunified" --max-time 10 2>&1 | head -5',
        'havoc appsync page')

    run(f'{CURL} -sL "https://havoc.app/package/ai.akemi.appsyncunified" --max-time 10 2>&1 | head -5',
        'havoc package info')

    # Chariz API
    print('\n=== Chariz repo search ===')
    run(f'{CURL} -sL "https://repo.chariz.com/api/packages/ai.akemi.appsyncunified" --max-time 10 2>&1 | head -5',
        'chariz appsync API')

    # Check if Packages index has it
    run(S + f'apt-cache show ai.akemi.appsyncunified 2>/dev/null | head -10',
        'apt show appsync')

    # Try adding akemi as a .list source (different format)
    akemi_list = 'deb https://cydia.akemi.ai/ ./'
    run(S + f'echo "{akemi_list}" > /var/jb/etc/apt/sources.list.d/akemi.list 2>/dev/null; echo done',
        'add akemi .list')
    run(S + f'{APT} update 2>&1 | grep -E "cydia.akemi|Error|Hit" | head -5', 'update with akemi list', timeout=30)
    run(S + f'apt-cache show ai.akemi.appsyncunified 2>/dev/null | head -5', 'appsync available?')

    # If available, install
    o, _ = run(S + f'apt-cache show ai.akemi.appsyncunified 2>/dev/null | grep "^Version"', 'version check')
    if 'Version' in o:
        run(S + f'{APT} install -y --allow-unauthenticated ai.akemi.appsyncunified 2>&1 | tail -8',
            'install AppSync!', timeout=120)
        run(S + 'ls /var/jb/Library/MobileSubstrate/DynamicLibraries/ | grep -i appsync',
            'verify AppSync dylib')
        run(S + 'launchctl kill SIGKILL system/com.apple.mobile.installd 2>/dev/null; sleep 2',
            'restart installd')
        print('\n  AppSync installed! Retry the IPA install now.')
    else:
        print('\n  AppSync not available from any source.')
        print('  Use Sideloadly (sideloadly.io) to sign and install the IPA.')

    c.close()
finally:
    fwd.terminate()
