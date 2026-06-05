import subprocess, sys, time, paramiko

fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', '2222', '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
time.sleep(2)
try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=2222, username='mobile', password='one', timeout=10)

    def run(cmd, label=''):
        _, out, err = c.exec_command(cmd)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        if label: print(f'--- {label} ---')
        if o: print(o)
        if e and 'grep' not in cmd: print('  err:', e[:300])

    # Check if apt can find python
    run('apt-cache search python 2>/dev/null | grep -i "^python3 " | head -5', 'apt python3')
    run('apt-cache search clang 2>/dev/null | head -5', 'apt clang')

    # Try to spawn a process and run code via opainject
    run('ls /var/jb/usr/lib/*.dylib 2>/dev/null | head -10', 'available dylibs')

    # Check if we can use lldb or gdb
    run('which lldb gdb 2>/dev/null || echo "no debugger"', 'debuggers')

    # Check Substrate/libhooker for injection APIs
    run('ls /var/jb/usr/lib/libsubstrate* /var/jb/usr/lib/libhooker* 2>/dev/null || echo "none"', 'hook libs')

    # Check if there's a simtouch or similar already installed
    run(
        'find /var/jb /usr /Library -name "SimulateTouch*" -o -name "simtouch*" '
        '-o -name "*GSTouchEnvelope*" 2>/dev/null || echo "none"',
        'SimulateTouch'
    )

    c.close()
finally:
    fwd.terminate()
