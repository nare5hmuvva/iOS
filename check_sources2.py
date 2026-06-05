import subprocess, sys, time, paramiko

fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', '2224', '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)

try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=2224, username='mobile', password='one', timeout=12)
    S = 'echo one | /var/jb/usr/bin/sudo -S -p "" '

    def run(cmd, label=''):
        _, out, err = c.exec_command(cmd, timeout=90)
        rc = out.channel.recv_exit_status()
        o = out.read().decode(errors='replace').strip()
        e = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        print(f'[{label or cmd[:60]}]')
        if txt: print('  ' + txt[:800].replace('\n', '\n  '))
        return o

    # Read .sources files
    run(S + 'cat /var/jb/etc/apt/sources.list.d/default.sources', 'default.sources')
    run(S + 'cat /var/jb/etc/apt/sources.list.d/procursus.sources', 'procursus.sources')
    run(S + 'cat /var/jb/etc/apt/sources.list.d/sileo.sources', 'sileo.sources')

    # Check what packages are available in procursus
    run(S + 'apt-cache search wget curl 2>/dev/null', 'wget/curl in apt')
    run(S + 'apt-get install -y --allow-unauthenticated wget 2>&1 | tail -5', 'install wget')
    run(S + 'apt-get install -y --allow-unauthenticated curl 2>&1 | tail -5', 'install curl')
    run(S + 'which wget curl /var/jb/usr/bin/wget /var/jb/usr/bin/curl 2>/dev/null', 'dl tools after install')

    # Add frida repo (build.frida.re)
    frida_src = (
        'Types: deb\n'
        'URIs: https://build.frida.re\n'
        'Suites: frida\n'
        'Components: main\n'
    )
    sftp = c.open_sftp()
    import io
    sftp.putfo(io.BytesIO(frida_src.encode()), '/tmp/frida.sources')
    sftp.close()
    run(S + 'cp /tmp/frida.sources /var/jb/etc/apt/sources.list.d/frida.sources', 'add frida repo')

    # Add AppSync repo
    appsync_src = (
        'Types: deb\n'
        'URIs: https://cydia.akemi.ai/\n'
        'Suites: ./\n'
        'Components: \n'
    )
    sftp = c.open_sftp()
    sftp.putfo(io.BytesIO(appsync_src.encode()), '/tmp/appsync.sources')
    sftp.close()
    run(S + 'cp /tmp/appsync.sources /var/jb/etc/apt/sources.list.d/appsync.sources', 'add appsync repo')

    # Update and search
    run(S + 'apt-get update 2>&1 | tail -8', 'apt update', )
    run(S + 'apt-cache search frida 2>/dev/null | head -10', 'frida in apt after update')
    run(S + 'apt-cache search appsync 2>/dev/null | head -5', 'appsync in apt after update')

    c.close()
finally:
    fwd.terminate()
