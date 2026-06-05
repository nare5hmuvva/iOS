"""Fix root SSH access on Dopamine jailbreak.
Connects as mobile, uses /var/jb/usr/bin/sudo to set root password
and enable root SSH login.
"""
import subprocess, sys, time, paramiko

MOBILE_PORT = 2222   # change if your forward uses a different port
MOBILE_PASS = 'one'
NEW_ROOT_PASS = 'alpine'

def start_forward(port):
    proc = subprocess.Popen(
        [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward',
         str(port), '22'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(3)
    return proc

fwd = start_forward(MOBILE_PORT)

try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting as mobile on port {MOBILE_PORT}...")
    c.connect('127.0.0.1', port=MOBILE_PORT, username='mobile',
              password=MOBILE_PASS, timeout=12)
    print("mobile SSH: OK")

    def run(cmd, label='', timeout=30):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        print(f"--- {label} ---")
        if o: print(o)
        if e: print("  err:", e[:300])
        return o

    # Check current su situation
    run('id', 'mobile id')
    run('which su || echo no-su', 'which su')
    run('ls -la /var/jb/usr/bin/su 2>&1 || echo missing', 'jb su')

    # Method 1: Use sudo to set root password
    print("\n--- Setting root password via sudo ---")
    sudocmd = f'echo "{MOBILE_PASS}" | /var/jb/usr/bin/sudo -S -p "" /bin/sh -c "echo -e \'{NEW_ROOT_PASS}\\n{NEW_ROOT_PASS}\' | passwd root" 2>&1'
    run(sudocmd, 'passwd root attempt 1')

    # Method 2: Try with /var/jb shell
    sudocmd2 = f'echo "{MOBILE_PASS}" | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/sh -c "printf \'{NEW_ROOT_PASS}\\n{NEW_ROOT_PASS}\\n\' | /var/jb/usr/bin/passwd root" 2>&1'
    run(sudocmd2, 'passwd root attempt 2 (jb shell)')

    # Method 3: Direct echo to shadow file via sudo
    # This directly sets root password using openssl
    sudocmd3 = (
        f'echo "{MOBILE_PASS}" | /var/jb/usr/bin/sudo -S -p "" '
        f'/var/jb/usr/bin/sh -c '
        f'"HASH=$(openssl passwd -1 \'{NEW_ROOT_PASS}\'); '
        f'sed -i \\"s|^root:[^:]*:|root:$HASH:|\\" /etc/master.passwd; '
        f'echo done"'
    )
    run(sudocmd3, 'shadow edit via openssl')

    # Check if root SSH is allowed
    run('grep -E "PermitRootLogin|PasswordAuthentication" /etc/ssh/sshd_config 2>/dev/null || echo no-sshd-config', 'sshd_config check')

    # Enable root SSH login
    enable_ssh = (
        f'echo "{MOBILE_PASS}" | /var/jb/usr/bin/sudo -S -p "" '
        f'/var/jb/usr/bin/sh -c "'
        f'sed -i \\"s/^#*PermitRootLogin.*/PermitRootLogin yes/\\" /etc/ssh/sshd_config; '
        f'sed -i \\"s/^#*PasswordAuthentication.*/PasswordAuthentication yes/\\" /etc/ssh/sshd_config; '
        f'echo sshd_config updated"'
    )
    run(enable_ssh, 'enable root SSH')

    # Restart sshd
    run(f'echo "{MOBILE_PASS}" | /var/jb/usr/bin/sudo -S -p "" '
        f'launchctl kickstart -k system/com.openssh.sshd 2>&1 || '
        f'echo "try killing sshd"', 'restart sshd')

    c.close()
    time.sleep(2)

    # Now try root login
    print("\n--- Testing root SSH login ---")
    c2 = paramiko.SSHClient()
    c2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c2.connect('127.0.0.1', port=MOBILE_PORT, username='root',
                   password=NEW_ROOT_PASS, timeout=10)
        _, out, _ = c2.exec_command('id && echo ROOT_ACCESS_OK')
        result = out.read().decode().strip()
        print(result)
        if 'ROOT_ACCESS_OK' in result:
            print(f"\nSUCCESS: root SSH works with password '{NEW_ROOT_PASS}'")
        c2.close()
    except Exception as e:
        print(f"root login still failed: {e}")
        print(f"\nManual fix: From your mobile SSH session run:")
        print(f"  /var/jb/usr/bin/sudo -s")
        print(f"  (enter password: {MOBILE_PASS})")
        print(f"  then: passwd root")
        print(f"  (set password: {NEW_ROOT_PASS})")

finally:
    fwd.terminate()
