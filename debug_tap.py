"""
Debug touch injection:
1. Test normalized coords (0.0-1.0) vs logical points â€” the API may expect normalized
2. Re-inject a debug dylib that logs whether HID client/events are created
3. Try dispatching on main queue (dispatch_async to main) vs background thread
"""
import subprocess, sys, time, paramiko

DEBUG_HOOK_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <dispatch/dispatch.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <mach/mach_time.h>
#include <CoreFoundation/CoreFoundation.h>
#include <Foundation/Foundation.h>

typedef void*  IOHIDEventSystemClientRef;
typedef struct __IOHIDEvent* IOHIDEventRef;

extern IOHIDEventSystemClientRef IOHIDEventSystemClientCreate(
    CFAllocatorRef alloc, int type, int flags, void *p, int n);
extern void IOHIDEventSystemClientDispatchEvent(
    IOHIDEventSystemClientRef c, IOHIDEventRef e);
extern IOHIDEventRef IOHIDEventCreateDigitizerFingerEvent(
    CFAllocatorRef alloc, uint64_t ts,
    uint32_t index, uint32_t identity, uint32_t eventMask,
    double x, double y, double z,
    double tipPressure, double twist,
    int range, int touch, uint32_t options);
extern IOHIDEventRef IOHIDEventCreateDigitizerEvent(
    CFAllocatorRef alloc, uint64_t ts,
    uint32_t transducerType,
    uint32_t index, uint32_t identity, uint32_t eventMask,
    uint32_t buttonMask,
    double x, double y, double z,
    double tipPressure, double barrelPressure,
    int range, int touch, uint32_t options);
extern void IOHIDEventAppendEvent(IOHIDEventRef parent, IOHIDEventRef child, uint32_t options);

#define SOCK_PATH "/tmp/tap_sock"
/* iPhone 7 logical screen size */
#define SCR_W 375.0
#define SCR_H 667.0

static IOHIDEventSystemClientRef g_client = NULL;
static dispatch_queue_t g_q = NULL;

/*
 * Try sending with BOTH normalized AND logical-point coordinates so we can
 * compare in logs. The socket command decides which mode:
 *   tapn x y  â†’ normalized (x/SCR_W, y/SCR_H)
 *   tap  x y  â†’ raw logical points
 */
static void dispatch_touch(double x, double y, int down, int normalized) {
    if (!g_client) {
        NSLog(@"[tap_hook] ERROR: g_client is NULL");
        return;
    }

    double fx = normalized ? (x / SCR_W) : x;
    double fy = normalized ? (y / SCR_H) : y;

    uint64_t t = mach_absolute_time();
    uint32_t eMask = 3; /* Range(1)|Touch(2) */

    IOHIDEventRef finger = IOHIDEventCreateDigitizerFingerEvent(
        kCFAllocatorDefault, t, 0, 1, eMask,
        fx, fy, 0,
        down ? 1.0 : 0.0, 0,
        down, down, 0);

    NSLog(@"[tap_hook] finger=%p x=%.4f y=%.4f down=%d normalized=%d", (void*)finger, fx, fy, down, normalized);

    if (!finger) { NSLog(@"[tap_hook] ERROR: finger event is NULL"); return; }

    /* Wrap in a parent digitizer event (required on newer iOS) */
    IOHIDEventRef parent = IOHIDEventCreateDigitizerEvent(
        kCFAllocatorDefault, t,
        2, /* kIOHIDDigitizerTransducerTypeHand */
        0, 0, eMask, 0,
        fx, fy, 0,
        down ? 1.0 : 0.0, 0,
        down, down, 0);

    if (parent) {
        IOHIDEventAppendEvent(parent, finger, 0);
        IOHIDEventSystemClientDispatchEvent(g_client, parent);
        NSLog(@"[tap_hook] dispatched via parent event");
        CFRelease(parent);
    } else {
        NSLog(@"[tap_hook] parent NULL, dispatching finger directly");
        IOHIDEventSystemClientDispatchEvent(g_client, finger);
    }
    CFRelease(finger);
}

static void do_tap(double x, double y, int normalized) {
    /* Dispatch on main queue â€” HID events may need the main run loop */
    dispatch_sync(g_q, ^{
        dispatch_touch(x, y, 1, normalized);
        usleep(80000);
        dispatch_touch(x, y, 0, normalized);
    });
}

static void do_swipe(double x1, double y1, double x2, double y2, int steps, int normalized) {
    if (steps < 5) steps = 20;
    dispatch_sync(g_q, ^{
        dispatch_touch(x1, y1, 1, normalized);
        for (int i = 1; i <= steps; i++) {
            usleep(16000);
            dispatch_touch(x1+(x2-x1)*i/steps, y1+(y2-y1)*i/steps, 1, normalized);
        }
        usleep(30000);
        dispatch_touch(x2, y2, 0, normalized);
    });
}

static void* sock_thread(void* _) {
    unlink(SOCK_PATH);
    int srv = socket(AF_UNIX, SOCK_STREAM, 0);
    if (srv < 0) return NULL;
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strlcpy(addr.sun_path, SOCK_PATH, sizeof(addr.sun_path));
    if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) < 0) return NULL;
    chmod(SOCK_PATH, 0666);
    listen(srv, 8);
    NSLog(@"[tap_hook] socket ready, g_client=%p", (void*)g_client);

    while (1) {
        int cl = accept(srv, NULL, NULL);
        if (cl < 0) continue;
        char buf[256] = {0};
        read(cl, buf, sizeof(buf)-1);
        double x, y, x2, y2; int steps = 20;

        if (strncmp(buf, "tapn", 4) == 0 && sscanf(buf+4, " %lf %lf", &x, &y) == 2) {
            /* tap with normalized coords */
            do_tap(x, y, 1);
            write(cl, "ok\n", 3);
        } else if (strncmp(buf, "tap", 3) == 0 && sscanf(buf+3, " %lf %lf", &x, &y) == 2) {
            /* tap with raw logical-point coords */
            do_tap(x, y, 0);
            write(cl, "ok\n", 3);
        } else if (strncmp(buf, "swipe", 5) == 0 &&
                   sscanf(buf+5, " %lf %lf %lf %lf %d", &x, &y, &x2, &y2, &steps) >= 4) {
            do_swipe(x, y, x2, y2, steps, 0);
            write(cl, "ok\n", 3);
        } else {
            write(cl, "err\n", 4);
        }
        close(cl);
    }
    return NULL;
}

__attribute__((constructor))
static void tap_hook_init(void) {
    /* Create HID client on main queue */
    g_q = dispatch_get_main_queue();
    dispatch_async(g_q, ^{
        g_client = IOHIDEventSystemClientCreate(kCFAllocatorDefault, 0, 0, NULL, 0);
        NSLog(@"[tap_hook] init: g_client=%p", (void*)g_client);
    });

    pthread_t t;
    pthread_attr_t a;
    pthread_attr_init(&a);
    pthread_attr_setdetachstate(&a, PTHREAD_CREATE_DETACHED);
    pthread_create(&t, &a, sock_thread, NULL);
    pthread_attr_destroy(&a);
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

    def run(cmd, label='', timeout=20):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        print(f'--- {label} ---')
        if o: print(o)
        if e: print('  err:', e[:400])
        print()
        return o

    sftp = c.open_sftp()
    with sftp.open('/tmp/tap_hook_debug.c', 'w') as f: f.write(DEBUG_HOOK_C)
    sftp.close()

    # Build
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -shared -fPIC -framework CoreFoundation -framework IOKit -framework Foundation '
        '-o /var/jb/usr/lib/tap_hook.dylib /tmp/tap_hook_debug.c 2>&1"; echo compile:$?',
        'compile debug dylib', timeout=60)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/lib/tap_hook.dylib && echo signed',
        'sign')

    # Get SpringBoard PID and inject
    sb_line = run('ps -A | grep SpringBoard | grep -v grep', 'sb pid')
    sb_pid = None
    for line in sb_line.splitlines():
        parts = line.split()
        if parts:
            try: sb_pid = int(parts[0]); break
            except ValueError: pass
    print(f'>>> SpringBoard PID: {sb_pid}')

    if sb_pid:
        # Kill old socket first
        run('echo one | /var/jb/usr/bin/sudo -S -p "" rm -f /tmp/tap_sock', 'remove old socket')
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {sb_pid} /var/jb/usr/lib/tap_hook.dylib 2>&1',
            'opainject')
        time.sleep(2)

        run('ls -la /tmp/tap_sock 2>/dev/null || echo "no socket"', 'socket')

        print('=== Test A: raw logical coords (187, 333) ===')
        print('>>> WATCH SCREEN <<<')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" '
            '/var/jb/usr/bin/tap_client tap 187 333; echo exit:$?', 'tap raw coords')
        time.sleep(1)

        print('=== Test B: normalized coords (0.5, 0.5) via tapn command ===')
        print('>>> WATCH SCREEN <<<')
        # Send "tapn 187 333" â€” dylib will normalize these
        run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
            '"echo \'tapn 187 333\' | python3 -c \\"import sys,socket; s=socket.socket(socket.AF_UNIX); '
            's.connect(\'/tmp/tap_sock\'); s.send(sys.stdin.buffer.read()); print(s.recv(10))\\"" 2>&1',
            'tap normalized coords')
        time.sleep(1)

        # Check NSLog output (last 20 lines of syslog mentioning tap_hook)
        run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
            '"grep -i tap_hook /var/log/syslog 2>/dev/null | tail -20 || '
            'grep -i tap_hook /var/mobile/Library/Logs/CrashReporter/systemlogs/*.log 2>/dev/null | tail -20 || '
            'echo no syslog found"',
            'syslog tap_hook entries')

    c.close()
finally:
    fwd.terminate()
