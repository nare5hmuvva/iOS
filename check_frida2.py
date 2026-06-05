import asyncio
import threading
import time
import socket

async def forward_ssh():
    """Forward USB port 22 to localhost:2222 using pymobiledevice3."""
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.usbmux import MuxConnection
    lockdown = await create_using_usbmux()
    udid = lockdown.identifier
    print(f'Device UDID: {udid}')
    return udid

# Try frida Python client (USB mode — no IP needed)
print('=== Trying frida USB client ===')
try:
    import frida
    print('frida Python package version:', frida.__version__)
    mgr = frida.get_device_manager()
    devices = mgr.enumerate_devices()
    print('Frida devices:', [str(d) for d in devices])
    usb = frida.get_usb_device(timeout=5)
    print('USB device:', usb)
    procs = usb.enumerate_processes()
    print(f'Got {len(procs)} processes via frida')
    frida_procs = [p for p in procs if 'frida' in p.name.lower()]
    print('Frida-related processes:', frida_procs)
except ImportError:
    print('frida Python package not installed')
    print('Install with: pip install frida-tools')
except Exception as e:
    print(f'frida error: {type(e).__name__}: {e}')

# Try to port-forward 22 via pymobiledevice3 usbmux
print()
print('=== Trying pymobiledevice3 iproxy (port 22 -> localhost:2222) ===')
try:
    import subprocess, sys, os
    result = subprocess.run(
        [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', '2222', '22', '--no-color'],
        capture_output=True, text=True, timeout=3
    )
    print('stdout:', result.stdout[:200])
    print('stderr:', result.stderr[:200])
except subprocess.TimeoutExpired:
    print('forward command started (timeout is expected for a daemon)')
except Exception as e:
    print(f'iproxy: {type(e).__name__}: {e}')
