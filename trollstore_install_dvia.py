"""Use TrollStore's trollstorehelper to install DVIA-v2 IPA — no AppSync needed."""
import subprocess, sys, time, paramiko
from pathlib import Path

USB_PORT   = 2224
MOBILE_PWD = 'one'

home = Path.home()
IPA_SEARCH_DIRS = [
    home / 'Desktop',
    home / 'Downloads',
    Path(__file__).parent,
]
ipa_path = None
for d in IPA_SEARCH_DIRS:
    for p in Path(d).rglob('*.ipa'):
        if 'dvia' in p.name.lower() or 'DVIA' in p.name:
            ipa_path = p
            break
    if ipa_path:
        break

print(f'IPA found: {ipa_path}' if ipa_path else 'No DVIA IPA found on Windows')

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
        if txt: print('    ' + txt[:500].replace('\n', '\n    '))
        return o, rc

    # ── Find trollstorehelper binary ──────────────────────────────────────────
    print('\n=== Find trollstorehelper ===')
    helper_path, _ = run(
        'find /var/jb /usr /var/containers/Bundle/Application -name "trollstorehelper" '
        '-not -path "*/TrollStore.app/*" 2>/dev/null | head -5',
        'find helper binary')

    # Also check dpkg file list
    run(S + 'dpkg -L com.opa334.trollstorehelper 2>/dev/null', 'dpkg files')

    # TrollStore.app itself has trollstorehelper
    ts_helper = '/var/containers/Bundle/Application/745A8484-2379-4118-8F2A-5E73986FCAC3/TrollStore.app/trollstorehelper'
    run(f'ls -la "{ts_helper}" 2>/dev/null || echo not_there', 'TrollStore.app helper')

    # Find any trollstorehelper
    all_helpers, _ = run(
        'find / -name "trollstorehelper" 2>/dev/null | grep -v proc | head -10',
        'all trollstorehelper paths')

    # Determine best helper path
    best_helper = None
    for line in all_helpers.splitlines():
        line = line.strip()
        if line and 'proc' not in line:
            best_helper = line
            # Prefer the one NOT inside TrollStore.app bundle for running
            if 'TrollStore.app' not in line:
                break
    if not best_helper:
        best_helper = ts_helper

    print(f'\n  Using helper: {best_helper}')
    run(f'ls -la "{best_helper}" 2>/dev/null', 'helper stat')

    # ── Upload DVIA IPA if available ─────────────────────────────────────────
    if ipa_path and ipa_path.exists():
        print(f'\n=== Uploading {ipa_path.name} ({ipa_path.stat().st_size // 1024}KB) ===')
        sftp = c.open_sftp()
        sftp.put(str(ipa_path), '/tmp/DVIA-v2.ipa')
        sftp.close()
        print('  Uploaded to /tmp/DVIA-v2.ipa')

        # Install via trollstorehelper
        print('\n=== Installing via trollstorehelper ===')
        run(f'"{best_helper}" install /tmp/DVIA-v2.ipa 2>&1', 'trollstorehelper install', timeout=60)
        run(f'find /var/containers/Bundle/Application -name "Info.plist" 2>/dev/null '
            f'| xargs grep -l "DVIAswiftv2" 2>/dev/null | head -1',
            'DVIA installed?')
    else:
        print('\n=== IPA not found on Windows ===')
        print('  Place the DVIA-v2.ipa in one of these locations and re-run:')
        for d in IPA_SEARCH_DIRS:
            print(f'    {d}')
        print()
        print('  OR use TrollStore on the device directly:')
        print('  1. Open TrollStore on iPhone')
        print('  2. Tap Apps -> + (top right)')
        print('  3. Select DVIA-v2.ipa from Files')
        print('  4. Tap Install')
        print()
        print('  To transfer IPA to device via Files app:')
        print('  - Connect iPhone to Windows')
        print('  - Open File Explorer -> iPhone -> Files app folder')
        print('  - Copy the IPA there')
        print('  - Then open TrollStore -> Apps -> install from Files')

    # ── Also show TrollStore status ───────────────────────────────────────────
    print('\n=== TrollStore status ===')
    run(f'"{best_helper}" --version 2>/dev/null || "{best_helper}" version 2>/dev/null || echo unknown_version',
        'TrollStore version')

    c.close()
finally:
    fwd.terminate()
    print('\nDone.')
