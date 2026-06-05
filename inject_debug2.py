"""
Respring SpringBoard (forcing dylib unload), then re-inject with:
- File-based logging (no NSLog/Foundation, pure C)
- Test both raw and normalized coordinates
- dispatch_async to main queue for IOHIDEvent calls
- Parent digitizer event wrapper
"""
import subprocess, sys, time, paramiko

DEBUG2_C = r"""
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
#define LOG_PATH  "/tmp/tap_hook.log"

/* iPhone 7: 375Ã—667 logical points */
#define SCR_W 375.0
#define SCR_H 667.0

static IOHIDEventSystemClientRef g_client = NULL;

static void logf(const char* fmt, ...) {
    FILE* f = fopen(LOG_PATH, "a");
    if (!f) return;
    va_list ap; va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap);
    fclose(f);
}

/* raw=1: use x,y as-is;  raw=0: normalize x/SCR_W, y/SCR_H */
static void dispatch_touch_raw(double x, double y, int down) {
    uint64_t t = mach_absolute_time();
    uint32_t eMask = 3; /* kIOHIDDigitizerEventRange|kIOHIDDigitizerEventTouch */

    IOHIDEventRef finger = IOHIDEventCreateDigitizerFingerEvent(
        kCFAllocatorDefault, t,
        0, 1, eMask,
        x, y, 0,
        down ? 1.0 : 0.0, 0,
        down, down, 0);

    logf("[touch] x=%.4f y=%.4f down=%d client=%p finger=%p\n",
         x, y, down, (void*)g_client, (void*)finger);

    if (!finger) { logf("[touch] ERROR: finger NULL\n"); return; }

    IOHIDEventRef parent = IOHIDEventCreateDigitizerEvent(
        kCFAllocatorDefault, t,
        2, /* kIOHIDDigitizerTransducerTypeHand */
        0, 0, eMask, 0,
        x, y, 0,
        down ? 1.0 : 0.0, 0,
        down, down, 0);

    if (parent) {
        IOHIDEventAppendEvent(parent, finger, 0);
        IOHIDEventSystemClientDispatchEvent(g_client, parent);
        logf("[touch] dispatched via parent\n");
        CFRelease(parent);
    } else {
        IOHIDEventSystemClientDispatchEvent(g_client, finger);
        logf("[touch] dispatched finger directly (no parent)\n");
    }
    CFRelease(finger);
}

typedef struct { double x, y; int down, normalize; int fd; } TouchArgs;

static void send_touch_on_main(double x, double y, int down, int normalize) {
    double fx = normalize ? x / SCR_W : x;
    double fy = normalize ? y / SCR_H : y;
    dispatch_touch_raw(fx, fy, down);
}

static void handle_tap(double x, double y, int normalize, int fd) {
    /* dispatch_async to main queue: IOHIDEvent must be sent from main run loop */
    double *args = malloc(4 * sizeof(double));
    args[0] = x; args[1] = y; args[2] = normalize; args[3] = fd;
    dispatch_async(dispatch_get_main_queue(), ^{
        send_touch_on_main(args[0], args[1], 1, (int)args[2]);
        usleep(80000);
        send_touch_on_main(args[0], args[1], 0, (int)args[2]);
        write((int)args[3], "ok\n", 3);
        close((int)args[3]);
        free(args);
    });
}

static void handle_swipe(double x1, double y1, double x2, double y2, int steps, int fd) {
    if (steps < 5) steps = 20;
    int st = steps;
    dispatch_async(dispatch_get_main_queue(), ^{
        send_touch_on_main(x1, y1, 1, 0);
        for (int i = 1; i <= st; i++) {
            usleep(16000);
            send_touch_on_main(x1+(x2-x1)*i/st, y1+(y2-y1)*i/st, 1, 0);
        }
        usleep(30000);
        send_touch_on_main(x2, y2, 0, 0);
        write(fd, "ok\n", 3);
        close(fd);
    });
}

static void* sock_thread(void* _) {
    unlink(SOCK_PATH);
    int srv = socket(AF_UNIX, SOCK_STREAM, 0);
    if (srv < 0) { logf("[sock] socket() failed\n"); return NULL; }
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strlcpy(addr.sun_path, SOCK_PATH, sizeof(addr.sun_path));
    if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        logf("[sock] bind failed\n"); return NULL;
    }
    chmod(SOCK_PATH, 0666);
    listen(srv, 8);
    logf("[sock] ready at %s, g_client=%p\n", SOCK_PATH, (void*)g_client);

    while (1) {
        int cl = accept(srv, NULL, NULL);
        if (cl < 0) continue;
        char buf[256] = {0};
        read(cl, buf, sizeof(buf)-1);
        logf("[sock] cmd: %s\n", buf);

        double x, y, x2, y2; int steps = 20;
        if (strncmp(buf, "tapn", 4) == 0 && sscanf(buf+4, " %lf %lf", &x, &y) == 2) {
            handle_tap(x, y, 1, cl);  /* normalized */
        } else if (strncmp(buf, "tap", 3) == 0 && sscanf(buf+3, " %lf %lf", &x, &y) == 2) {
            handle_tap(x, y, 0, cl);  /* raw logical points */
        } else if (strncmp(buf, "swipe", 5) == 0 &&
                   sscanf(buf+5, " %lf %lf %lf %lf %d", &x, &y, &x2, &y2, &steps) >= 4) {
            handle_swipe(x, y, x2, y2, steps, cl);
        } else {
            write(cl, "err\n", 4);
            close(cl);
        }
    }
    return NULL;
}

__attribute__((constructor))
static void tap_hook_init(void) {
    logf("=== tap_hook loaded ===\n");
    dispatch_async(dispatch_get_main_queue(), ^{
        g_client = IOHIDEventSystemClientCreate(kCFAllocatorDefault, 0, 0, NULL, 0);
        logf("[init] g_client created: %p\n", (void*)g_client);
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

    def run(cmd, label='', timeout=30):
        _, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode().strip()
        e = err.read().decode().strip()
        print(f'--- {label} ---')
        if o: print(o)
        if e: print('  err:', e[:400])
        print()
        return o

    sftp = c.open_sftp()
    with sftp.open('/tmp/tap_hook_dbg.c', 'w') as f: f.write(DEBUG2_C)
    sftp.close()

    # Compile
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -shared -fPIC -framework CoreFoundation -framework IOKit '
        '-o /var/jb/usr/lib/tap_hook.dylib /tmp/tap_hook_dbg.c 2>&1"; echo compile:$?',
        'compile debug2 dylib', timeout=60)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/lib/tap_hook.dylib && echo signed',
        'sign')

    # Respring to force SpringBoard to unload old dylib
    print('=== Respringing SpringBoard to unload old dylib ===')
    run('echo one | /var/jb/usr/bin/sudo -S -p "" killall -9 SpringBoard 2>&1', 'respring')
    print('Waiting 8s for SpringBoard to restart...')
    time.sleep(8)

    # Get new SpringBoard PID
    sb_line = run('ps -A | grep SpringBoard | grep -v grep', 'new sb pid')
    sb_pid = None
    for line in sb_line.splitlines():
        parts = line.split()
        if parts:
            try: sb_pid = int(parts[0]); break
            except ValueError: pass
    print(f'>>> New SpringBoard PID: {sb_pid}')

    if sb_pid:
        # Remove old log
        run('echo one | /var/jb/usr/bin/sudo -S -p "" rm -f /tmp/tap_hook.log /tmp/tap_sock', 'cleanup')

        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {sb_pid} /var/jb/usr/lib/tap_hook.dylib 2>&1',
            'opainject')
        time.sleep(2)

        run('ls -la /tmp/tap_sock 2>/dev/null || echo "no socket"', 'socket check')
        run('cat /tmp/tap_hook.log 2>/dev/null || echo "no log"', 'initial log')

        print('=== Test A: raw logical coords (187, 333) â€” WATCH SCREEN ===')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" '
            '/var/jb/usr/bin/tap_client tap 187 333; echo exit:$?', 'tap raw')
        time.sleep(1)
        run('cat /tmp/tap_hook.log', 'log after raw tap')

        print('=== Test B: normalized coords (tapn 187 333 â†’ 0.499, 0.499) â€” WATCH SCREEN ===')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
            '"echo \'tapn 187 333\' > /tmp/tap_cmd && '
            'python3 -c \\"'
            'import socket; s=socket.socket(socket.AF_UNIX); '
            's.connect(\\\'/tmp/tap_sock\\\'); '
            's.send(open(\\\'/tmp/tap_cmd\\\',\\\'rb\\\').read()); '
            'print(s.recv(10))\\"  2>&1"',
            'tap normalized via python socket')
        time.sleep(1)
        run('cat /tmp/tap_hook.log', 'log after normalized tap')

    c.close()
finally:
    fwd.terminate()
