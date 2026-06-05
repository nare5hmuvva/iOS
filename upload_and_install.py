"""Download debs on Windows, upload via SFTP, install on device."""
import subprocess, sys, time, paramiko, urllib.request, os, io
from pathlib import Path

USB_PORT   = 2224
MOBILE_PWD = 'one'

DEBS = {
    'appsync.deb': 'https://cydia.akemi.ai/debs/ai.akemi.appsyncunified_116.0_iphoneos-arm64.deb',
    'frida.deb':   'https://github.com/frida/frida/releases/download/16.7.19/frida-server_16.7.19_iphoneos-arm64.deb',
}

TMP = Path(r'c:\Users\muvva\Desktop\iOS_Project\tmp_debs')
TMP.mkdir(exist_ok=True)

# ── 1. Download debs on Windows ───────────────────────────────────────────────
print('=== Downloading debs on Windows ===')
for fname, url in DEBS.items():
    dest = TMP / fname
    if dest.exists() and dest.stat().st_size > 100_000:
        print(f'  {fname}: already cached ({dest.stat().st_size // 1024}KB)')
        continue
    print(f'  Downloading {fname} from {url[:60]}...')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/8.0'})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, 'wb') as f:
            data = r.read()
            f.write(data)
        print(f'    -> {len(data)//1024}KB saved')
    except Exception as e:
        print(f'    ERROR: {e}')

# ── 2. Connect SSH + SFTP ─────────────────────────────────────────────────────
print('\n=== Connecting to device ===')
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
    print('  SSH OK')

    S = f'echo "{MOBILE_PWD}" | /var/jb/usr/bin/sudo -S -p "" '

    def run(cmd, label='', timeout=120):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        rc = out.channel.recv_exit_status()
        o  = out.read().decode(errors='replace').strip()
        e  = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        tag = 'OK' if rc == 0 else f'rc={rc}'
        print(f'  [{tag}] {label or cmd[:50]}')
        if txt: print('    ' + txt[:400].replace('\n', '\n    '))
        return o, rc

    # ── 3. Upload debs via SFTP ───────────────────────────────────────────────
    print('\n=== Uploading debs via SFTP ===')
    sftp = c.open_sftp()
    for fname in DEBS:
        local = TMP / fname
        remote = f'/tmp/{fname}'
        if local.exists() and local.stat().st_size > 100_000:
            sftp.put(str(local), remote)
            print(f'  uploaded {fname} ({local.stat().st_size // 1024}KB) -> {remote}')
        else:
            print(f'  SKIP {fname}: not downloaded')
    sftp.close()

    # ── 4. Fix root password ──────────────────────────────────────────────────
    print('\n=== Fix root password ===')
    # Use Python on device to set root password hash directly
    run(S + "python3 -c \""
        "import subprocess, crypt; "
        "h = crypt.crypt('alpine', crypt.mksalt(crypt.METHOD_SHA512)); "
        "subprocess.run(['chsh', '-s', '/bin/bash', 'root']); "
        "print(h)"
        "\" 2>/dev/null || echo python3_not_available", 'python3 approach')

    # Use OpenSSL to generate hash and write to /etc/master.passwd
    run(S + "/var/jb/usr/bin/sh -c \""
        "HASH=$(openssl passwd -1 'alpine'); "
        "echo HASH=$HASH; "
        "cp /etc/master.passwd /etc/master.passwd.bak; "
        "sed -i 's|^root:[^:]*:|root:'\"$HASH\"':|' /etc/master.passwd; "
        "pwd_mkdb /etc/master.passwd 2>&1 || echo pwd_mkdb_done"
        "\"", 'set root hash via openssl')

    run(S + 'grep "^root:" /etc/master.passwd | head -1', 'root entry')

    # ── 5. Install AppSync ────────────────────────────────────────────────────
    print('\n=== Install AppSync Unified ===')
    run(S + '/var/jb/usr/bin/dpkg -i --force-all /tmp/appsync.deb 2>&1 | tail -8',
        'install AppSync', timeout=60)
    run(S + 'ls /var/jb/Library/MobileSubstrate/DynamicLibraries/AppSync* 2>/dev/null || echo MISSING',
        'AppSync verify')

    # Restart installd
    run(S + 'launchctl kill SIGKILL system/com.apple.mobile.installd 2>/dev/null; sleep 2',
        'restart installd')

    # ── 6. Install frida-server 16.7.19 ──────────────────────────────────────
    print('\n=== Install frida-server 16.7.19 ===')
    run(S + '/var/jb/usr/bin/dpkg -i --force-all /tmp/frida.deb 2>&1 | tail -8',
        'install frida', timeout=60)

    # Kill old, start new
    run(S + 'killall frida-server 2>/dev/null; '
        'launchctl kill SIGTERM system/re.frida.server 2>/dev/null; '
        'sleep 1; /var/jb/usr/sbin/frida-server -D &',
        'start frida-server')
    time.sleep(3)
    run('ps aux | grep frida-server | grep -v grep', 'frida running?')

    # ── 7. Summary ───────────────────────────────────────────────────────────
    print('\n=== Summary ===')
    run('dpkg -l | grep -E "ellekit|appsync|frida"', 'installed packages')
    run('ls /var/jb/Library/MobileSubstrate/DynamicLibraries/', 'dylibs')
    run('/var/jb/usr/sbin/frida-server --version 2>/dev/null || echo missing',
        'frida-server version')

    print('\n=== Next: Install DVIA-v2 ===')
    print('  Now go to dashboard and use Install IPA with your DVIA-v2.ipa file')
    print('  OR place DVIA-v2.ipa in:', TMP.parent)

    c.close()

finally:
    fwd.terminate()
    print('\nDone.')
