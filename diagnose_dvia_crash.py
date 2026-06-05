"""Diagnose DVIA-v2 crash on launch â€” connects via direct WiFi IP."""
import sys, time, paramiko

import sys as _sys, os as _os; _sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from config_loader import cfg as _cfg
IPHONE_IP = _cfg['IPHONE_IP'] or '192.168.1.50'
PORT      = 22
USER      = 'mobile'
PASSWD    = 'one'
BUNDLE_ID = 'com.highaltitudehacks.DVIAswiftv2'

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"Connecting to {IPHONE_IP}:{PORT} as {USER}...")
c.connect(IPHONE_IP, port=PORT, username=USER, password=PASSWD, timeout=15)
print("SSH OK\n")

def run(cmd, label='', timeout=60):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode(errors='replace').strip()
    e = err.read().decode(errors='replace').strip()
    print(f"=== {label} ===")
    if o: print(o[:3000])
    if e and e != o: print("  STDERR:", e[:400])
    print()
    return o

# 1. Check if app is installed
run(f'find /var/containers/Bundle/Application -name "Info.plist" 2>/dev/null'
    f' | xargs grep -l "{BUNDLE_ID}" 2>/dev/null | head -3',
    'App install path')

# 2. Most recent crash log
crash_files = run(
    'ls -t /private/var/mobile/Library/Logs/CrashReporter/ 2>/dev/null'
    ' | grep -i -E "DVIA|DVIAswift" | head -5',
    'DVIA crash log files')

# Get content of most recent crash
run(
    'f=$(ls -t /private/var/mobile/Library/Logs/CrashReporter/ 2>/dev/null'
    ' | grep -i -E "DVIA|DVIAswift" | head -1);'
    ' [ -n "$f" ] && cat "/private/var/mobile/Library/Logs/CrashReporter/$f"'
    ' | head -100 || echo "no crash log found"',
    'Latest crash log content')

# 3. AppSync status
run('ls /var/jb/Library/MobileSubstrate/DynamicLibraries/ 2>/dev/null',
    'All injected dylibs')

run('ls -la /var/jb/Library/MobileSubstrate/DynamicLibraries/AppSync* 2>/dev/null'
    ' || echo "AppSync dylibs NOT FOUND"',
    'AppSync dylib check')

# 4. Check the binary's architecture and signing
app_dir = run(
    f'find /var/containers/Bundle/Application -name "Info.plist" 2>/dev/null'
    f' | xargs grep -l "{BUNDLE_ID}" 2>/dev/null | head -1 | xargs dirname',
    'App directory')

if app_dir and '/var/containers' in app_dir:
    run(f'ls "{app_dir}/"', 'App bundle contents')

    # Find the main executable
    binary = run(
        f'/var/jb/usr/bin/plutil -key CFBundleExecutable "{app_dir}/Info.plist" 2>/dev/null'
        f' || grep -A1 CFBundleExecutable "{app_dir}/Info.plist" | tail -1 | sed "s/.*<string>\\(.*\\)<\\/string>.*/\\1/"',
        'Main executable name')

    if binary:
        binary_path = f'{app_dir}/{binary.strip()}'
        run(f'ls -la "{binary_path}"', 'Binary file info')
        run(f'file "{binary_path}" 2>/dev/null || xxd "{binary_path}" | head -2',
            'Binary type (arm64 check)')
        run(f'/var/jb/usr/bin/ldid -e "{binary_path}" 2>/dev/null | head -40'
            f' || echo "ldid -e failed (no entitlements or ldid missing)"',
            'Binary entitlements')

# 5. installd patch check
run('ps aux | grep installd | grep -v grep', 'installd process')
run('grep -r "AppSync" /var/jb/Library/MobileSubstrate/DynamicLibraries/ 2>/dev/null | head -5',
    'AppSync plist filter')

c.close()
print("Diagnostic complete.")
