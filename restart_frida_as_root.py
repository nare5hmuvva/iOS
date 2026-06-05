"""
Restart frida-server as root on Dopamine rootless jailbreak.
Fixes: "unable to access process with pid 1" when spawning apps via Frida.
"""
import subprocess, sys, time, paramiko

USB_PORT   = 2224
MOBILE_PWD = 'one'
PLIST      = '/var/jb/Library/LaunchDaemons/re.frida.server.plist'

fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', str(USB_PORT), '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)

try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=USB_PORT, username='mobile', password=MOBILE_PWD, timeout=12)
    print('SSH OK')

    S = f'echo {MOBILE_PWD} | /var/jb/usr/bin/sudo -S -p "" '

    def run(cmd, label='', timeout=30):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        rc  = out.channel.recv_exit_status()
        o   = out.read().decode(errors='replace').strip()
        e   = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        tag = 'OK' if rc == 0 else f'rc={rc}'
        print(f'  [{tag}] {label or cmd[:70]}')
        if txt: print('   ', txt[:400].replace('\n', '\n    '))
        return o, rc

    # 1. Show current plist
    print('\n=== Current frida-server plist ===')
    run(f'cat {PLIST} 2>/dev/null || echo "plist not found"', 'plist content')

    # 2. Check frida-server binary location
    run('find /var/jb -name "frida-server" 2>/dev/null | head -5', 'frida-server binary')

    # 3. Stop frida-server
    print('\n=== Stopping frida-server ===')
    run(S + f'/var/jb/bin/launchctl unload {PLIST} 2>/dev/null; killall -9 frida-server 2>/dev/null; echo stopped',
        'stop')
    time.sleep(2)

    # 4. Patch plist to remove UserName key (runs as root by default without it)
    print('\n=== Patching plist to run as root ===')
    patch = (
        S + r"""python3 -c "
import plistlib, os
path = '/var/jb/Library/LaunchDaemons/re.frida.server.plist'
with open(path, 'rb') as f:
    d = plistlib.load(f)
# Remove UserName so launchd runs it as root
changed = False
if 'UserName' in d:
    print('Removing UserName:', d.pop('UserName'))
    changed = True
# Ensure it has the right program args
print('ProgramArguments:', d.get('ProgramArguments'))
if changed:
    with open(path, 'wb') as f:
        plistlib.dump(d, f)
    print('Plist updated')
else:
    print('No UserName key found - already runs as root (or check manually)')
" 2>&1"""
    )
    run(patch, 'patch plist')

    # 5. Reload and start
    print('\n=== Starting frida-server as root ===')
    run(S + f'/var/jb/bin/launchctl load {PLIST} 2>/dev/null; echo loaded', 'launchctl load')
    time.sleep(3)

    # 6. Verify
    print('\n=== Verification ===')
    out, _ = run('ps aux | grep frida-server | grep -v grep', 'frida-server process')
    if 'frida-server' in out:
        # Check if running as root
        if out.strip().startswith('root') or ' root ' in out.split('frida')[0]:
            print('\n  ✓ frida-server is running as ROOT — spawn will work now.')
        else:
            print(f'\n  frida-server running as: {out.split()[0]}')
            print('  If not root, try the manual fix below.')
    else:
        print('\n  frida-server not running — trying direct launch as root...')
        binary, _ = run('find /var/jb -name "frida-server" 2>/dev/null | head -1', '')
        if binary.strip():
            run(S + f'nohup {binary.strip()} -l 0.0.0.0:27042 > /tmp/frida.log 2>&1 &', 'direct launch')
            time.sleep(2)
            run('ps aux | grep frida-server | grep -v grep', 'verify')

    print('\n=== Done ===')
    print('Now retry Spawn + Inject in the dashboard.')
    c.close()
finally:
    fwd.terminate()
