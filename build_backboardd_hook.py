"""Inject IOHIDEvent dispatch dylib into backboardd.
backboardd IS the HID server â€” IOHIDEventSystemClientDispatchEvent
called from within backboardd is a loopback that bypasses all entitlement checks.
IPC: SpringBoard writes /tmp/tap_cmd + notify_post("com.lab.hid.cmd")
     backboardd reads /tmp/tap_cmd + dispatches IOHIDEvent + writes /tmp/tap_resp
"""
import subprocess, sys, time, paramiko

HOOK_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>
#include <pthread.h>
#include <sys/stat.h>
#include <stdarg.h>
#include <errno.h>
#include <mach/mach_time.h>
#include <CoreFoundation/CoreFoundation.h>
#include <notify.h>

#define CMD_PATH  "/tmp/tap_cmd"
#define RESP_PATH "/tmp/tap_resp"
#define LOG_PATH  "/tmp/taphook.log"

static FILE* g_logf = NULL;
static void tlog(const char* fmt, ...) {
    if (!g_logf) return;
    va_list ap; va_start(ap, fmt);
    vfprintf(g_logf, fmt, ap); fputc('\n', g_logf); fflush(g_logf);
    va_end(ap);
}

typedef struct __IOHIDEvent* IOHIDEventRef;
typedef struct __IOHIDEventSystemClient* IOHIDEventSystemClientRef;
typedef uint64_t IOHIDTimestamp;
typedef uint32_t IOHIDDigitizerEventMask;
typedef uint32_t IOHIDDigitizerTransducerType;
typedef uint32_t IOHIDEventOptionBits;

static IOHIDEventRef (*fp_CreateFingerEvent)(
    CFAllocatorRef, IOHIDTimestamp,
    uint32_t, uint32_t, IOHIDDigitizerEventMask,
    double, double, double,
    float, float,
    Boolean, Boolean,
    IOHIDEventOptionBits) = NULL;

static IOHIDEventRef (*fp_CreateDigitizerEvent)(
    CFAllocatorRef, IOHIDTimestamp,
    IOHIDDigitizerTransducerType,
    uint32_t, uint32_t, IOHIDDigitizerEventMask,
    double, double, double,
    float, float,
    Boolean, Boolean,
    IOHIDEventOptionBits) = NULL;

static void (*fp_AppendEvent)(IOHIDEventRef, IOHIDEventRef, IOHIDEventOptionBits) = NULL;
static IOHIDEventSystemClientRef (*fp_CreateClient)(CFAllocatorRef, uint32_t) = NULL;
static void (*fp_DispatchEvent)(IOHIDEventSystemClientRef, IOHIDEventRef) = NULL;
static void (*fp_CFRelease)(CFTypeRef) = NULL;

static IOHIDEventSystemClientRef g_client = NULL;

#define kIOHIDDigitizerEventMaskPosition 0x100
#define kIOHIDDigitizerEventMaskRange    0x004
#define kIOHIDDigitizerEventMaskTouch    0x010
#define kIOHIDDigitizerEventMaskAll      (kIOHIDDigitizerEventMaskPosition|kIOHIDDigitizerEventMaskRange|kIOHIDDigitizerEventMaskTouch)
#define kIOHIDDigitizerTransducerTypeHand 4

static void dispatch_finger(double sx, double sy,
                             float pressure, Boolean range, Boolean touch,
                             IOHIDTimestamp ts) {
    IOHIDEventRef finger = fp_CreateFingerEvent(
        kCFAllocatorDefault, ts,
        0, 1,
        kIOHIDDigitizerEventMaskAll,
        sx, sy, 0.0,
        pressure, 0.0,
        range, touch,
        0);
    if (!finger) { tlog("finger nil"); return; }

    if (fp_CreateDigitizerEvent) {
        IOHIDEventRef parent = fp_CreateDigitizerEvent(
            kCFAllocatorDefault, ts,
            kIOHIDDigitizerTransducerTypeHand,
            0, 1,
            kIOHIDDigitizerEventMaskAll,
            sx, sy, 0.0,
            pressure, 0.0,
            range, touch,
            0);
        if (parent) {
            fp_AppendEvent(parent, finger, 0);
            fp_DispatchEvent(g_client, parent);
            fp_CFRelease(parent);
        } else {
            fp_DispatchEvent(g_client, finger);
        }
    } else {
        fp_DispatchEvent(g_client, finger);
    }
    fp_CFRelease(finger);
}

static int do_tap(double x, double y) {
    if (!fp_CreateFingerEvent || !fp_DispatchEvent || !g_client) {
        tlog("do_tap: not ready"); return 1;
    }
    double sx = x / 375.0;
    double sy = y / 667.0;

    tlog("do_tap(%.1f,%.1f) -> normalized(%.3f,%.3f)", x, y, sx, sy);

    IOHIDTimestamp ts = mach_absolute_time();
    dispatch_finger(sx, sy, 1.0f, 1, 1, ts);
    tlog("touch down sent");

    usleep(80000);

    ts = mach_absolute_time();
    dispatch_finger(sx, sy, 0.0f, 0, 0, ts);
    tlog("touch up sent");
    return 0;
}

static int do_swipe(double x1, double y1, double x2, double y2, int steps) {
    if (!fp_CreateFingerEvent || !fp_DispatchEvent || !g_client) return 1;
    if (steps < 2) steps = 2;

    tlog("do_swipe(%.1f,%.1f -> %.1f,%.1f, %d steps)", x1, y1, x2, y2, steps);

    IOHIDTimestamp ts = mach_absolute_time();
    dispatch_finger(x1/375.0, y1/667.0, 1.0f, 1, 1, ts);

    int step_delay = 400000 / steps;
    for (int i = 1; i <= steps; i++) {
        usleep(step_delay);
        double t = (double)i / steps;
        double sx = (x1 + (x2-x1)*t) / 375.0;
        double sy = (y1 + (y2-y1)*t) / 667.0;
        ts = mach_absolute_time();

        IOHIDEventRef finger = fp_CreateFingerEvent(
            kCFAllocatorDefault, ts,
            0, 1,
            kIOHIDDigitizerEventMaskPosition,
            sx, sy, 0.0,
            1.0f, 0.0f,
            1, 1,
            0);
        if (finger) { fp_DispatchEvent(g_client, finger); fp_CFRelease(finger); }
    }

    usleep(20000);
    ts = mach_absolute_time();
    dispatch_finger(x2/375.0, y2/667.0, 0.0f, 0, 0, ts);
    tlog("swipe done");
    return 0;
}

static void handle_cmd(void) {
    FILE* f = fopen(CMD_PATH, "r");
    if (!f) { tlog("handle_cmd: no file (errno=%d)", errno); return; }
    char buf[256] = {0};
    fgets(buf, sizeof(buf)-1, f);
    fclose(f);
    // strip newline
    char* nl = strchr(buf, '\n');
    if (nl) *nl = 0;
    tlog("handle_cmd: [%s]", buf);

    double x, y, x2, y2;
    int steps;
    int result = 1;
    if (sscanf(buf, "tap %lf %lf", &x, &y) == 2)
        result = do_tap(x, y);
    else if (sscanf(buf, "swipe %lf %lf %lf %lf %d", &x, &y, &x2, &y2, &steps) == 5)
        result = do_swipe(x, y, x2, y2, steps);
    else
        tlog("handle_cmd: unknown [%s]", buf);

    FILE* rf = fopen(RESP_PATH, "w");
    if (rf) { fputs(result == 0 ? "ok" : "err", rf); fclose(rf); }
    tlog("handle_cmd: result=%d -> %s", result, result==0?"ok":"err");
}

static void load_iohid(void) {
    void* h = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit",
                     RTLD_GLOBAL | RTLD_LAZY);
    tlog("IOKit: %p", h);

    fp_CreateFingerEvent    = dlsym(RTLD_DEFAULT, "IOHIDEventCreateDigitizerFingerEvent");
    fp_CreateDigitizerEvent = dlsym(RTLD_DEFAULT, "IOHIDEventCreateDigitizerEvent");
    fp_AppendEvent          = dlsym(RTLD_DEFAULT, "IOHIDEventAppendEvent");
    fp_CreateClient         = dlsym(RTLD_DEFAULT, "IOHIDEventSystemClientCreate");
    fp_DispatchEvent        = dlsym(RTLD_DEFAULT, "IOHIDEventSystemClientDispatchEvent");
    fp_CFRelease            = dlsym(RTLD_DEFAULT, "CFRelease");

    tlog("CreateFingerEvent: %p", fp_CreateFingerEvent);
    tlog("CreateDigitizerEvent: %p", fp_CreateDigitizerEvent);
    tlog("AppendEvent: %p", fp_AppendEvent);
    tlog("CreateClient: %p", fp_CreateClient);
    tlog("DispatchEvent: %p", fp_DispatchEvent);

    if (fp_CreateClient) {
        g_client = fp_CreateClient(kCFAllocatorDefault, 0);
        tlog("IOHIDEventSystemClient: %p", g_client);
    }
}

__attribute__((constructor))
static void hook_init(void) {
    dispatch_after(
        dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)),
        dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0),
    ^{
        g_logf = fopen(LOG_PATH, "a");
        tlog("=== IOHIDEvent hook in backboardd PID %d ===", getpid());
        load_iohid();

        if (!fp_CreateFingerEvent || !fp_DispatchEvent || !g_client) {
            tlog("CRITICAL: IOHIDEvent functions not available");
            return;
        }

        // Register Darwin notification listener â€” no socket needed
        int token = 0;
        uint32_t nstatus = notify_register_dispatch(
            "com.lab.hid.cmd",
            &token,
            dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0),
            ^(int t) { handle_cmd(); });
        tlog("notify_register_dispatch: status=%u token=%d", nstatus, token);

        // Auto-tap center screen once to confirm IOHIDEvent dispatch works
        dispatch_after(
            dispatch_time(DISPATCH_TIME_NOW, (int64_t)(2.0 * NSEC_PER_SEC)),
            dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0),
        ^{
            tlog("=== AUTO-TAP TEST at (187,333) ===");
            int r = do_tap(187.0, 333.0);
            tlog("auto-tap result: %d", r);
        });

        tlog("hook ready â€” waiting for com.lab.hid.cmd notifications");
    });
}
"""

fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', '2222', '22'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
time.sleep(2)

try:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect('127.0.0.1', port=2222, username='mobile', password='one', timeout=10)

    def run(cmd, label='', timeout=60):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        print(f'--- {label} ---')
        if o: print(o)
        if e: print('  err:', e[:400])
        print()
        return o

    sftp = c.open_sftp()
    with sftp.open('/tmp/tap_bb_hook.c', 'w') as f: f.write(HOOK_C)
    sftp.close()

    # Compile
    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/clang '
        '-isysroot /var/jb/usr/share/SDKs/iPhoneOS.sdk '
        '-dynamiclib '
        '-framework CoreFoundation '
        '-Wl,-undefined,dynamic_lookup '
        '-o /var/jb/usr/lib/tap_bb_hook.dylib /tmp/tap_bb_hook.c 2>&1',
        'compile bb hook', timeout=90)

    out = run('ls -la /var/jb/usr/lib/tap_bb_hook.dylib 2>&1', 'check dylib')
    if 'No such file' in out:
        print('COMPILATION FAILED'); c.close(); exit(1)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/lib/tap_bb_hook.dylib; echo signed:$?', 'sign')

    # Get backboardd PID
    pid_out = run('ps -A | grep backboardd | grep -v grep', 'backboardd pid')
    bb_pid = None
    for line in pid_out.splitlines():
        parts = line.split()
        if parts:
            try: bb_pid = int(parts[0]); break
            except ValueError: pass
    print(f'backboardd PID: {bb_pid}')

    if bb_pid:
        run('echo one | /var/jb/usr/bin/sudo -S -p "" rm -f /tmp/taphook.log /tmp/tap_cmd /tmp/tap_resp', 'clean')
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {bb_pid} /var/jb/usr/lib/tap_bb_hook.dylib 2>&1',
            f'inject into backboardd({bb_pid})')

        print('Waiting 4s for hook init + auto-tap...')
        time.sleep(4)

        run('cat /tmp/taphook.log 2>&1', 'init log')
        run('ps -A | grep backboardd | grep -v grep', 'backboardd still alive?')

        # Test manual tap via notification
        print('>>> WATCH SCREEN - manual tap test via notify <<<')
        run('echo "tap 187 333" > /tmp/tap_cmd && notify_post com.lab.hid.cmd 2>/dev/null || '
            'echo one | /var/jb/usr/bin/sudo -S -p "" /bin/sh -c '
            '"echo tap 187 333 > /tmp/tap_cmd && notifyutil -p com.lab.hid.cmd" 2>&1; echo done',
            'manual notify tap', timeout=10)
        time.sleep(2)
        run('cat /tmp/taphook.log 2>&1', 'log after manual tap')
        run('cat /tmp/tap_resp 2>/dev/null || echo "(no resp file)"', 'tap_resp')
        run('ps -A | grep backboardd | grep -v grep', 'backboardd alive after tap?')
    else:
        print('ERROR: backboardd PID not found')

    c.close()
finally:
    fwd.terminate()
