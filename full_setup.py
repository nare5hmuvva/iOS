"""Full device setup after re-jailbreak.
1. Fix root SSH access
2. Install frida-server 16.7.19
3. Install AppSync Unified + ElleKit
4. Install DVIA-v2 IPA
5. Start frida-server
6. Diagnose DVIA crash
"""
import subprocess, sys, time, paramiko, os
from pathlib import Path

IPHONE_IP  = '192.168.29.44'
USB_PORT   = 2224
MOBILE_PWD = 'one'
ROOT_PWD   = 'alpine'
IPA_PATH   = Path(r'c:\Users\muvva\Desktop\iOS_Project') / 'DVIA-v2.ipa'

# ── helpers ───────────────────────────────────────────────────────────────────
def start_fwd(port):
    p = subprocess.Popen(
        [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward',
         str(port), '22'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    return p

def ssh_connect(port, user, pwd, retries=3):
    for i in range(retries):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect('127.0.0.1', port=port, username=user, password=pwd, timeout=12)
            return c
        except Exception as e:
            if i == retries - 1: raise
            print(f'  retry {i+1}: {e}')
            time.sleep(2)

def run(c, cmd, label='', timeout=120, ok_codes=(0,)):
    _, out, err = c.exec_command(cmd, timeout=timeout, get_pty=False)
    rc = out.channel.recv_exit_status()
    o = out.read().decode(errors='replace').strip()
    e = err.read().decode(errors='replace').strip()
    combined = (o + '\n' + e).strip()
    status = '✓' if rc in ok_codes else f'✗(rc={rc})'
    print(f'  [{status}] {label or cmd[:60]}')
    if combined: print('    ' + combined[:400].replace('\n', '\n    '))
    return o, e, rc

# ── Step 1: connect as mobile ─────────────────────────────────────────────────
print('\n══ Step 1: SSH as mobile ══')
fwd = start_fwd(USB_PORT)
try:
    c = ssh_connect(USB_PORT, 'mobile', MOBILE_PWD)
    print('  ✓ mobile SSH OK')

    run(c, 'id', 'whoami')
    run(c, 'uname -a', 'device info')
    run(c, 'ls /var/jb/usr/bin/sudo 2>/dev/null || echo missing', 'sudo check')

    # ── Step 2: fix root access ───────────────────────────────────────────────
    print('\n══ Step 2: Fix root access ══')

    # Set root password using sudo
    set_root_pwd_cmd = (
        f'echo "{MOBILE_PWD}" | /var/jb/usr/bin/sudo -S -p "" '
        f'/var/jb/usr/bin/sh -c '
        f'"printf \'{ROOT_PWD}\\n{ROOT_PWD}\\n\' | passwd root 2>&1; echo passwd_done"'
    )
    run(c, set_root_pwd_cmd, f'set root password to {ROOT_PWD}', ok_codes=(0,1))

    # Enable root SSH
    run(c,
        f'echo "{MOBILE_PWD}" | /var/jb/usr/bin/sudo -S -p "" '
        f'/var/jb/usr/bin/sh -c \''
        f'cfg=/etc/ssh/sshd_config; '
        f'grep -q "PermitRootLogin" $cfg && '
        f'  sed -i "s/.*PermitRootLogin.*/PermitRootLogin yes/" $cfg || '
        f'  echo "PermitRootLogin yes" >> $cfg; '
        f'grep -q "PasswordAuthentication" $cfg && '
        f'  sed -i "s/.*PasswordAuthentication.*/PasswordAuthentication yes/" $cfg || '
        f'  echo "PasswordAuthentication yes" >> $cfg; '
        f'echo sshd_config_done\'',
        'enable root SSH login', ok_codes=(0,1))

    # Reload sshd
    run(c,
        f'echo "{MOBILE_PWD}" | /var/jb/usr/bin/sudo -S -p "" '
        f'launchctl kickstart -k system/com.openssh.sshd 2>&1 || echo skipped',
        'reload sshd', ok_codes=(0,1))

    c.close()
    time.sleep(2)

    # ── Step 3: re-connect as root ────────────────────────────────────────────
    print('\n══ Step 3: Connect as root ══')
    try:
        cr = ssh_connect(USB_PORT, 'root', ROOT_PWD)
        print('  ✓ root SSH OK')
        run(cr, 'id', 'root check')
    except Exception as e:
        print(f'  root login failed: {e} — continuing as mobile via sudo')
        cr = ssh_connect(USB_PORT, 'mobile', MOBILE_PWD)
        SUDO = f'echo "{MOBILE_PWD}" | /var/jb/usr/bin/sudo -S -p "" '
    else:
        SUDO = ''

    def srun(cmd, label='', timeout=180, ok_codes=(0,)):
        return run(cr, SUDO + cmd if SUDO else cmd, label, timeout, ok_codes)

    # ── Step 4: check existing packages ──────────────────────────────────────
    print('\n══ Step 4: Package check ══')
    srun('dpkg -l | grep -E "ellekit|appsync|frida" || echo none', 'installed packages')
    srun('ls /var/jb/Library/MobileSubstrate/DynamicLibraries/ 2>/dev/null || echo empty',
         'DynamicLibraries')

    # ── Step 5: Install ElleKit ───────────────────────────────────────────────
    print('\n══ Step 5: Install ElleKit ══')
    srun('apt-get update -y 2>&1 | tail -3', 'apt update', timeout=60, ok_codes=(0,1))

    # Add ellekit repo if needed
    srun('grep -r "ellekit" /etc/apt/sources.list* 2>/dev/null || '
         'echo "deb https://ellekit.space/apt /" >> /etc/apt/sources.list.d/ellekit.list',
         'ellekit repo', ok_codes=(0,1))

    srun('apt-get update -y 2>&1 | tail -3', 'apt update after repo add',
         timeout=60, ok_codes=(0,1))

    srun('apt-get install -y --allow-unauthenticated ellekit 2>&1 | tail -5',
         'install ElleKit', timeout=120, ok_codes=(0,1))

    # ── Step 6: Install AppSync Unified ──────────────────────────────────────
    print('\n══ Step 6: Install AppSync Unified ══')
    srun('grep -r "cydia.akemi" /etc/apt/sources.list* 2>/dev/null || '
         'echo "deb https://cydia.akemi.ai/ ./" >> /etc/apt/sources.list.d/akemi.list',
         'AppSync repo', ok_codes=(0,1))

    srun('apt-get update -y 2>&1 | tail -3', 'apt update after AppSync repo',
         timeout=60, ok_codes=(0,1))

    srun('apt-get install -y --allow-unauthenticated appinst org.thebigboss.repo.icons 2>&1 | tail -5',
         'install appinst (alternative)', timeout=120, ok_codes=(0,1))

    srun('apt-get install -y --allow-unauthenticated ai.akemi.appsyncunified 2>&1 | tail -5',
         'install AppSync Unified', timeout=120, ok_codes=(0,1))

    # Verify AppSync
    srun('ls /var/jb/Library/MobileSubstrate/DynamicLibraries/AppSync* 2>/dev/null || echo NOT_FOUND',
         'AppSync dylib check')

    # Kill installd so ElleKit reloads into fresh instance
    srun('launchctl kill SIGKILL system/com.apple.mobile.installd 2>&1 || '
         'killall -9 installd 2>&1 || echo skip', 'restart installd', ok_codes=(0,1))
    time.sleep(3)

    # ── Step 7: Install frida-server 16.7.19 ─────────────────────────────────
    print('\n══ Step 7: Install frida-server 16.7.19 ══')

    # Check if already installed
    o, _, _ = srun('frida-server --version 2>/dev/null || '
                   '/var/jb/usr/sbin/frida-server --version 2>/dev/null || echo missing',
                   'current frida-server version')

    if '16.7.19' not in o:
        # Download frida 16.7.19 deb for arm64
        deb_url = 'https://github.com/frida/frida/releases/download/16.7.19/frida-server_16.7.19_iphoneos-arm64.deb'
        srun(f'curl -L -o /tmp/frida_16.7.19.deb "{deb_url}" 2>&1 | tail -3',
             'download frida 16.7.19', timeout=120, ok_codes=(0,1))
        srun('dpkg -i --force-all /tmp/frida_16.7.19.deb 2>&1 | tail -5',
             'install frida deb', timeout=60, ok_codes=(0,1))
    else:
        print('  frida-server 16.7.19 already installed')

    # Start frida-server
    srun('launchctl kill SIGTERM system/re.frida.server 2>/dev/null; '
         'killall frida-server 2>/dev/null; sleep 1; '
         '/var/jb/usr/sbin/frida-server -D &',
         'start frida-server', ok_codes=(0,1))
    time.sleep(2)
    srun('ps aux | grep frida-server | grep -v grep', 'frida running?')

    # ── Step 8: diagnose DVIA ─────────────────────────────────────────────────
    print('\n══ Step 8: DVIA-v2 diagnosis ══')

    BUNDLE_ID = 'com.highaltitudehacks.DVIAswiftv2'
    srun(f'find /var/containers/Bundle/Application -name "Info.plist" 2>/dev/null'
         f' | xargs grep -l "{BUNDLE_ID}" 2>/dev/null | head -3',
         'DVIA installed?')

    # Get latest crash log
    crash_files, _, _ = srun(
        'ls -t /private/var/mobile/Library/Logs/CrashReporter/ 2>/dev/null'
        ' | grep -i -E "DVIA|DVIAswift" | head -3',
        'DVIA crash files')

    if crash_files and 'DVIA' in crash_files.upper():
        first = crash_files.strip().splitlines()[0]
        srun(f'head -60 "/private/var/mobile/Library/Logs/CrashReporter/{first}"',
             f'crash log: {first}')
    else:
        print('  No DVIA crash log found yet — app may not have been launched yet')

    # Check installd plist for AppSync
    srun('ls /var/jb/Library/MobileSubstrate/DynamicLibraries/ 2>/dev/null',
         'final DynamicLibraries state')

    cr.close()

finally:
    fwd.terminate()
    print('\n══ Setup complete ══')
