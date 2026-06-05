"""
Inject DVIA-v2 jailbreak detection bypass via Frida over USB.

Usage:
    python run_jb_bypass.py            # spawn DVIA-v2 fresh with bypass
    python run_jb_bypass.py --attach   # attach to already-running DVIA-v2
    python run_jb_bypass.py --pid 1234 # attach to specific PID
"""
import sys
import time
import argparse
from pathlib import Path

BUNDLE_ID   = 'com.highaltitudehacks.DVIAswiftv2'
SCRIPT_PATH = Path(__file__).parent / 'ios-pentest-lab' / 'frida-scripts' / 'dvia_jailbreak_bypass.js'

def on_message(msg, _data):
    if msg['type'] == 'send':
        payload = msg.get('payload', {})
        if isinstance(payload, dict):
            print(payload.get('message', ''))
    elif msg['type'] == 'error':
        print('[ERROR]', msg.get('description', msg))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attach', action='store_true', help='Attach to running DVIA-v2')
    parser.add_argument('--pid',    type=int,            help='Attach to specific PID')
    args = parser.parse_args()

    try:
        import frida
    except ImportError:
        sys.exit('frida not installed — run: pip install frida==16.7.19')

    script_src = SCRIPT_PATH.read_text(encoding='utf-8')

    print(f'[*] Connecting to USB device...')
    try:
        device = frida.get_usb_device(timeout=10)
    except frida.InvalidArgumentError:
        sys.exit('[!] No USB device found. Check: device connected, trusted, frida-server running.')

    print(f'[*] Device: {device.name}')

    if args.pid:
        print(f'[*] Attaching to PID {args.pid}...')
        session = device.attach(args.pid)

    elif args.attach:
        # Find running DVIA-v2
        procs = device.enumerate_processes()
        target = next((p for p in procs
                       if 'dvia' in p.name.lower() or BUNDLE_ID in (p.parameters or {}).get('path', '')),
                      None)
        if not target:
            sys.exit('[!] DVIA-v2 not running. Open it on the device first, or use spawn mode (drop --attach).')
        print(f'[*] Attaching to {target.name} (PID {target.pid})...')
        session = device.attach(target.pid)

    else:
        # Spawn — inject before any code runs (most reliable for early checks)
        print(f'[*] Spawning {BUNDLE_ID}...')
        try:
            pid = device.spawn([BUNDLE_ID])
        except frida.ExecutableNotFoundError:
            sys.exit(f'[!] {BUNDLE_ID} not installed on device.')
        session = device.attach(pid)
        script = session.create_script(script_src)
        script.on('message', on_message)
        print('[*] Loading bypass script...')
        script.load()
        print(f'[*] Resuming app (PID {pid})...')
        device.resume(pid)
        print('[*] DVIA-v2 launched with bypass active.')
        print('[*] Press Ctrl+C to stop.\n')
        try:
            sys.stdin.read()
        except KeyboardInterrupt:
            pass
        return

    # attach path
    script = session.create_script(script_src)
    script.on('message', on_message)
    print('[*] Loading bypass script...')
    script.load()
    print('[*] Bypass active. Press Ctrl+C to stop.\n')
    try:
        sys.stdin.read()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
