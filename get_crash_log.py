"""Pull latest DVIA crash log from device."""
import subprocess, sys, time, paramiko

USB_PORT   = 2224
MOBILE_PWD = 'one'

fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward',
     str(USB_PORT), '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)

try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=USB_PORT, username='mobile', password=MOBILE_PWD, timeout=12)

    def run(cmd, timeout=30):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        out.channel.recv_exit_status()
        return out.read().decode(errors='replace').strip()

    # Get latest crash log for DVIA
    crash_file = run(
        'ls -t /private/var/mobile/Library/Logs/CrashReporter/ 2>/dev/null'
        ' | grep -i dvia | head -1')
    print(f'Latest crash: {crash_file}')

    if crash_file:
        log = run(f'cat "/private/var/mobile/Library/Logs/CrashReporter/{crash_file}"', timeout=10)
        # Print key sections
        lines = log.splitlines()
        for i, line in enumerate(lines[:120]):
            print(line)
    else:
        print('No crash log yet — open DVIA-v2 on the device first, wait for crash, then re-run this.')

    c.close()
finally:
    fwd.terminate()
