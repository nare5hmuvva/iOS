"""Check SpringBoard's real entitlements + compile a clean minimal debug dylib."""
import subprocess, sys, time, paramiko

# Minimal, clean dylib â€” no naming conflicts, no extern inside functions
HOOK_V4 = r"""
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <mach/mach_time.h>
#include <dispatch/dispatch.h>
#include <CoreFoundation/CoreFoundation.h>

typedef void*  IOHIDEventSystemClientRef;
typedef struct __IOHIDEvent* IOHIDEventRef;

extern IOHIDEventSystemClientRef IOHIDEventSystemClientCreate(
    CFAllocatorRef, int, int, void*, int);
extern void IOHIDEventSystemClientDispatchEvent(
    IOHIDEventSystemClientRef, IOHIDEventRef);
extern IOHIDEventRef IOHIDEventCreateDigitizerFingerEvent(
    CFAllocatorRef, uint64_t, uint32_t, uint32_t, uint32_t,
    double, double, double, double, double, int, int, uint32_t);
extern IOHIDEventRef IOHIDEventCreateDigitizerEvent(
    CFAllocatorRef, uint64_t, uint32_t, uint32_t, uint32_t,
    uint32_t, uint32_t, double, double, double, double, double,
    int, int, uint32_t);
extern void IOHIDEventAppendEvent(IOHIDEventRef, IOHIDEventRef, uint32_t);

#define LOG_FILE  "/tmp/taphook.log"
#define SOCK_FILE "/tmp/tap_sock"

static IOHIDEventSystemClientRef s_client = NULL;

static void tlog(const char *fmt, ...) {
    FILE *f = fopen(LOG_FILE, "a");
    if (!f) return;
    va_list ap; va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap);
    fclose(f);
}

static void hid_finger(double x, double y, int down) {
    if (!s_client) { tlog("hid_finger: s_client is NULL!\n"); return; }
    uint64_t ts = mach_absolute_time();
    IOHIDEventRef finger = IOHIDEventCreateDigitizerFingerEvent(
        kCFAllocatorDefault, ts, 0, 1, 3,
        x, y, 0, down ? 1.0 : 0.0, 0,
        down, down, 0);
    tlog("hid_finger x=%.3f y=%.3f down=%d finger=%p\n", x, y, down, (void*)finger);
    if (!finger) return;

    /* wrap in parent digitizer event */
    IOHIDEventRef parent = IOHIDEventCreateDigitizerEvent(
        kCFAllocatorDefault, ts, 2, 0, 0, 3, 0,
        x, y, 0, down ? 1.0 : 0.0, 0, down, down, 0);
    if (parent) {
        IOHIDEventAppendEvent(parent, finger, 0);
        IOHIDEventSystemClientDispatchEvent(s_client, parent);
        tlog("  -> dispatched via parent\n");
        CFRelease(parent);
    } else {
        IOHIDEventSystemClientDispatchEvent(s_client, finger);
        tlog("  -> dispatched direct\n");
    }
    CFRelease(finger);
}

static void* taphook_server(void *arg) {
    (void)arg;
    unlink(SOCK_FILE);
    int srv = socket(AF_UNIX, SOCK_STREAM, 0);
    if (srv < 0) return NULL;
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCK_FILE, sizeof(addr.sun_path)-1);
    if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) < 0) return NULL;
    chmod(SOCK_FILE, 0666);
    listen(srv, 8);
    tlog("server ready s_client=%p\n", (void*)s_client);

    while (1) {
        int cl = accept(srv, NULL, NULL);
        if (cl < 0) continue;
        char buf[128] = {0};
        read(cl, buf, sizeof(buf)-1);
        tlog("cmd: %.80s\n", buf);

        double x = 0, y = 0;
        int norm = 0;
        const char *rest = buf;
        if (strncmp(buf, "tapn", 4) == 0) { norm = 1; rest = buf + 4; }
        else if (strncmp(buf, "tap", 3) == 0) { rest = buf + 3; }

        if (sscanf(rest, " %lf %lf", &x, &y) == 2) {
            double fx = norm ? x / 375.0 : x;
            double fy = norm ? y / 667.0 : y;
            dispatch_sync(dispatch_get_main_queue(), ^{
                hid_finger(fx, fy, 1);
                usleep(80000);
                hid_finger(fx, fy, 0);
            });
            write(cl, "ok\n", 3);
        } else {
            write(cl, "err\n", 4);
        }
        close(cl);
    }
    return NULL;
}

__attribute__((constructor))
static void taphook_init(void) {
    tlog("=== taphook_init ===\n");
    dispatch_async(dispatch_get_main_queue(), ^{
        s_client = IOHIDEventSystemClientCreate(kCFAllocatorDefault, 0, 0, NULL, 0);
        tlog("s_client=%p\n", (void*)s_client);
    });
    pthread_t t;
    pthread_attr_t a;
    pthread_attr_init(&a);
    pthread_attr_setdetachstate(&a, PTHREAD_CREATE_DETACHED);
    pthread_create(&t, &a, taphook_server, NULL);
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
        if e: print('  err:', e[:300])
        print()
        return o

    # 1. Check SpringBoard's real entitlements
    run('ldid -e /System/Library/CoreServices/SpringBoard.app/SpringBoard 2>&1 | head -40',
        'SpringBoard entitlements')

    # 2. Compile clean dylib
    sftp = c.open_sftp()
    with sftp.open('/tmp/taphook_v4.c', 'w') as f: f.write(HOOK_V4)
    sftp.close()

    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -shared -fPIC -framework CoreFoundation -framework IOKit '
        '-o /var/jb/usr/lib/tap_hook.dylib /tmp/taphook_v4.c 2>&1"; echo compile:$?',
        'compile v4', timeout=60)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/lib/tap_hook.dylib && echo signed',
        'sign')

    # 3. Respring + inject
    sb_line = run('ps -A | grep SpringBoard | grep -v grep', 'sb pid')
    sb_pid = None
    for line in sb_line.splitlines():
        parts = line.split()
        if parts:
            try: sb_pid = int(parts[0]); break
            except ValueError: pass

    run('echo one | /var/jb/usr/bin/sudo -S -p "" killall -9 SpringBoard', 'respring')
    print('Waiting 8s...')
    time.sleep(8)

    sb_line = run('ps -A | grep SpringBoard | grep -v grep', 'new sb pid')
    sb_pid = None
    for line in sb_line.splitlines():
        parts = line.split()
        if parts:
            try: sb_pid = int(parts[0]); break
            except ValueError: pass
    print(f'>>> SpringBoard PID: {sb_pid}')

    if sb_pid:
        run('echo one | /var/jb/usr/bin/sudo -S -p "" rm -f /tmp/taphook.log /tmp/tap_sock', 'clean')
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {sb_pid} /var/jb/usr/lib/tap_hook.dylib 2>&1', 'inject')
        time.sleep(2)

        run('ls /tmp/tap_sock && cat /tmp/taphook.log 2>/dev/null || echo no-log', 'socket+log')

        print('=== WATCH SCREEN: raw tap 187 333 ===')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/tap_client tap 187 333', 'tap raw')
        time.sleep(0.5)

        print('=== WATCH SCREEN: normalized tapn 187 333 ===')
        # tap_client sends "tap x y" â€” we need a way to send "tapn x y"
        # Use python3 on device to connect to socket
        run('echo one | /var/jb/usr/bin/sudo -S -p "" python3 -c "'
            'import socket; s=socket.socket(socket.AF_UNIX); '
            "s.connect('/tmp/tap_sock'); s.send(b'tapn 187 333'); "
            'print(s.recv(10))"', 'tapn normalized')
        time.sleep(0.5)

        run('cat /tmp/taphook.log', 'full log')

    c.close()
finally:
    fwd.terminate()
