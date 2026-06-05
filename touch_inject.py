#!/usr/bin/env python3
"""
Touch injection for jailbroken iOS using IOHIDEvent via ctypes.
Usage: python3 touch_inject.py tap <x> <y>
       python3 touch_inject.py swipe <x1> <y1> <x2> <y2> [steps]
Runs as root (via sudo).
"""
import sys, ctypes, time

iokit = ctypes.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
cf    = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
libc  = ctypes.CDLL('/usr/lib/libSystem.B.dylib')

iokit.IOHIDEventSystemClientCreate.restype  = ctypes.c_void_p
iokit.IOHIDEventSystemClientCreate.argtypes = [ctypes.c_void_p]
iokit.IOHIDEventSystemClientDispatchEvent.restype  = None
iokit.IOHIDEventSystemClientDispatchEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
iokit.IOHIDEventCreateDigitizerFingerEvent.restype  = ctypes.c_void_p
iokit.IOHIDEventCreateDigitizerFingerEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32,
    ctypes.c_uint32, ctypes.c_float, ctypes.c_float, ctypes.c_float,
    ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float,
    ctypes.c_uint32, ctypes.c_bool, ctypes.c_bool, ctypes.c_uint32,
]
cf.CFRelease.argtypes = [ctypes.c_void_p]
cf.CFRelease.restype  = None
libc.mach_absolute_time.restype  = ctypes.c_uint64
libc.mach_absolute_time.argtypes = []

SCREEN_W = 375.0
SCREEN_H = 667.0
kRange   = 0x00000001
kTouch   = 0x00000002

def make_event(x, y, touching):
    return iokit.IOHIDEventCreateDigitizerFingerEvent(
        None, libc.mach_absolute_time(), 0, 1, kRange | kTouch,
        x / SCREEN_W, y / SCREEN_H, 0.0,
        1.0 if touching else 0.0,
        0.0, 1.0, 1.0, 0, touching, touching, 0
    )

def tap(x, y):
    client = iokit.IOHIDEventSystemClientCreate(None)
    if not client:
        print("ERROR: IOHIDEventSystemClientCreate returned NULL", file=sys.stderr); sys.exit(1)
    try:
        for touching in (True, False):
            ev = make_event(x, y, touching)
            iokit.IOHIDEventSystemClientDispatchEvent(client, ev)
            cf.CFRelease(ev)
            if touching: time.sleep(0.05)
        print(f"tap {x},{y} ok")
    finally:
        cf.CFRelease(client)

def swipe(x1, y1, x2, y2, steps=20):
    client = iokit.IOHIDEventSystemClientCreate(None)
    if not client:
        print("ERROR: IOHIDEventSystemClientCreate returned NULL", file=sys.stderr); sys.exit(1)
    try:
        ev = make_event(x1, y1, True)
        iokit.IOHIDEventSystemClientDispatchEvent(client, ev); cf.CFRelease(ev)
        time.sleep(0.02)
        for i in range(1, steps + 1):
            px = x1 + (x2 - x1) * i / steps
            py = y1 + (y2 - y1) * i / steps
            ev = make_event(px, py, True)
            iokit.IOHIDEventSystemClientDispatchEvent(client, ev); cf.CFRelease(ev)
            time.sleep(0.02)
        ev = make_event(x2, y2, False)
        iokit.IOHIDEventSystemClientDispatchEvent(client, ev); cf.CFRelease(ev)
        print(f"swipe ({x1},{y1})->({x2},{y2}) ok")
    finally:
        cf.CFRelease(client)

if __name__ == '__main__':
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} tap <x> <y>"); sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'tap':
        tap(float(sys.argv[2]), float(sys.argv[3]))
    elif cmd == 'swipe' and len(sys.argv) >= 6:
        steps = int(sys.argv[7]) if len(sys.argv) > 7 else 20
        swipe(float(sys.argv[2]), float(sys.argv[3]),
              float(sys.argv[4]), float(sys.argv[5]), steps)
    else:
        print(f"Unknown: {sys.argv[1]}"); sys.exit(1)
