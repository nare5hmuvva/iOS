"""
Push mitmproxy CA cert to iPhone and install it to iOS trust store
via .mobileconfig profile so Safari + native apps trust it.
"""
import subprocess, sys, time, os, base64, ssl as _ssl, paramiko

CERT_PATH = os.path.join(os.path.expanduser('~'), '.mitmproxy', 'mitmproxy-ca-cert.pem')
USB_PORT  = 2223
PWD       = 'one'
SUDO      = 'echo one | /var/jb/usr/bin/sudo -S -p "" '

# ── Build mobileconfig on Windows ─────────────────────────────────────────────
with open(CERT_PATH, 'rb') as f:
    pem_data = f.read()

der_data = _ssl.PEM_cert_to_DER_cert(pem_data.decode())
b64_cert  = base64.b64encode(der_data).decode()

mobileconfig = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>PayloadContent</key>
  <array>
    <dict>
      <key>PayloadCertificateFileName</key><string>mitmproxy-ca.crt</string>
      <key>PayloadContent</key><data>{b64_cert}</data>
      <key>PayloadDescription</key><string>mitmproxy CA</string>
      <key>PayloadDisplayName</key><string>mitmproxy CA</string>
      <key>PayloadIdentifier</key><string>com.mitmproxy.ca.cert</string>
      <key>PayloadType</key><string>com.apple.security.root</string>
      <key>PayloadUUID</key><string>8F3F6A6F-1234-4444-BBBB-123456789ABC</string>
      <key>PayloadVersion</key><integer>1</integer>
    </dict>
  </array>
  <key>PayloadDisplayName</key><string>mitmproxy</string>
  <key>PayloadIdentifier</key><string>com.mitmproxy</string>
  <key>PayloadType</key><string>Configuration</string>
  <key>PayloadUUID</key><string>9A3E5B1C-5678-4444-CCCC-ABCDEF012345</string>
  <key>PayloadVersion</key><integer>1</integer>
</dict>
</plist>"""

# Write mobileconfig locally
mc_path = os.path.join(os.path.dirname(CERT_PATH), 'mitmproxy.mobileconfig')
with open(mc_path, 'w', encoding='utf-8') as f:
    f.write(mobileconfig)
print(f'mobileconfig written: {mc_path}')

# ── SSH to device ─────────────────────────────────────────────────────────────
fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', str(USB_PORT), '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)

try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=USB_PORT, username='mobile', password=PWD, timeout=10)
    print('SSH OK')

    def run(cmd, label=''):
        _, out, err = c.exec_command(cmd, timeout=15)
        rc = out.channel.recv_exit_status()
        o  = out.read().decode(errors='replace').strip()
        e  = err.read().decode(errors='replace').strip()
        txt = (o + ' ' + e).strip()
        print(f'  [{"OK" if rc==0 else f"rc={rc}"}] {label or cmd[:70]}')
        if txt: print('   ', txt[:300])
        return o, rc

    # Upload PEM and mobileconfig
    sftp = c.open_sftp()
    sftp.put(CERT_PATH, '/tmp/mitmproxy-ca.pem')
    sftp.put(mc_path,   '/tmp/mitmproxy.mobileconfig')
    sftp.close()
    print('Files uploaded.')

    # Copy PEM to openssl cert store (helps curl/wget/frida)
    run(SUDO + 'cp /tmp/mitmproxy-ca.pem /var/jb/etc/ssl/certs/mitmproxy-ca.pem 2>/dev/null && echo copied',
        'copy to ssl/certs')

    # Find iOS TrustStore database (different paths on different iOS versions)
    run('find /private/var/db /var/db -name "TrustStore.sqlite3" 2>/dev/null | head -3',
        'find TrustStore.sqlite3')

    # Try cfutil to install the profile (Dopamine/Sileo provides this)
    run('which cfutil || ls /var/jb/usr/bin/cfutil 2>/dev/null || echo no_cfutil', 'find cfutil')
    out, rc = run(SUDO + 'cfutil install -p /tmp/mitmproxy.mobileconfig 2>&1', 'cfutil install profile')
    if rc != 0:
        print('\n  cfutil failed. Manual cert install required (see steps below).')

    print()
    print('=' * 60)
    print('SETUP COMPLETE — NEXT STEPS')
    print('=' * 60)
    print()
    print('Step 1 — Set iPhone Wi-Fi proxy:')
    print('  Settings > Wi-Fi > tap your network > Configure Proxy')
    print('  Manual  |  Server: 192.168.29.102  |  Port: 8082')
    print()
    print('Step 2 — Install CA cert (if not done by cfutil above):')
    print('  On iPhone, open Safari and go to:  http://mitm.it')
    print('  Tap "Apple"  -> download profile')
    print('  Settings > General > VPN & Device Management')
    print('  -> mitmproxy -> Install -> Trust')
    print('  Settings > General > About > Certificate Trust Settings')
    print('  -> Enable full trust for mitmproxy')
    print()
    print('Step 3 — Intercept traffic:')
    print('  mitmweb UI:   http://localhost:8083')
    print()
    print('Step 4 — In dashboard (http://localhost:8081):')
    print('  Select Arista app -> SSL Pinning Bypass -> Spawn + Inject')
    print()
    c.close()
finally:
    fwd.terminate()
