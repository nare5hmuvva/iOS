"""Debug dylib v3: renamed log func, test raw/normalized/index variations."""
import subprocess, sys, time, paramiko

DEBUG3_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
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
#define SCR_W 375.0
#define SCR_H 667.0

static void tap_log(const char *fmt, ...) {
    FILE *f = fopen(LOG_PATH, "a");
    if (!f) return;
    va_list ap; va_start(ap, fmt); vfprintf(f, fmt, ap); va_end(ap);
    fclose(f);
}

/*
 * mode 0: raw logical points, index=0, no parent
 * mode 1: normalized (x/375,y/667), index=0, no parent
 * mode 2: raw logical points, index=1, no parent
 * mode 3: raw logical points, index=0, WITH parent event
 * mode 4: new client per call (raw, index=0, no parent)
 */
static void do_touch(double x, double y, int down, int mode) {
    double fx = (mode == 1) ? x / SCR_W : x;
    double fy = (mode == 1) ? y / SCR_H : y;
    uint32_t idx = (mode == 2) ? 1 : 0;
    uint64_t t = mach_absolute_time();
    uint32_t eMask = 3;  /* Range(1)|Touch(2) */

    IOHIDEventSystemClientRef cli;
    if (mode == 4) {
        cli = IOHIDEventSystemClientCreate(kCFAllocatorDefault, 0, 0, NULL, 0);
    } else {
        /* use cached client â€” created in constructor on main queue */
        extern IOHIDEventSystemClientRef g_client;
        cli = g_client;
    }
    tap_log("do_touch mode=%d x=%.4f y=%.4f down=%d cli=%p\n", mode, fx, fy, down, (void*)cli);

    IOHIDEventRef finger = IOHIDEventCreateDigitizerFingerEvent(
        kCFAllocatorDefault, t,
        idx, 1, eMask,
        fx, fy, 0,
        down ? 1.0 : 0.0, 0,
        down, down, 0);
    tap_log("  finger=%p\n", (void*)finger);
    if (!finger) { tap_log("  ERROR: finger NULL\n"); return; }

    if (mode == 3) {
        IOHIDEventRef parent = IOHIDEventCreateDigitizerEvent(
            kCFAllocatorDefault, t, 2, 0, 0, eMask, 0,
            fx, fy, 0, down ? 1.0 : 0.0, 0, down, down, 0);
        if (parent) {
            IOHIDEventAppendEvent(parent, finger, 0);
            IOHIDEventSystemClientDispatchEvent(cli, parent);
            tap_log("  dispatched via parent\n");
            CFRelease(parent);
        }
    } else {
        IOHIDEventSystemClientDispatchEvent(cli, finger);
        tap_log("  dispatched direct\n");
    }
    CFRelease(finger);
    if (mode == 4 && cli) CFRelease(cli);
}

static IOHIDEventSystemClientRef g_client = NULL;

static void* sock_thread(void *_) {
    unlink(SOCK_PATH);
    int srv = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strlcpy(addr.sun_path, SOCK_PATH, sizeof(addr.sun_path));
    bind(srv, (struct sockaddr*)&addr, sizeof(addr));
    chmod(SOCK_PATH, 0666);
    listen(srv, 8);
    tap_log("sock ready, g_client=%p\n", (void*)g_client);

    while (1) {
        int cl = accept(srv, NULL, NULL);
        if (cl < 0) continue;
        char buf[256] = {0};
        read(cl, buf, sizeof(buf)-1);
        tap_log("cmd: %.80s\n", buf);

        double x, y; int mode = 0;
        /* protocol: "tap <x> <y> <mode>" */
        if (sscanf(buf, "tap %lf %lf %d", &x, &y, &mode) >= 2) {
            dispatch_sync(dispatch_get_main_queue(), ^{
                do_touch(x, y, 1, mode);
                usleep(80000);
                do_touch(x, y, 0, mode);
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
static void tap_hook_init(void) {
    tap_log("=== tap_hook v3 loaded ===\n");
    dispatch_async(dispatch_get_main_queue(), ^{
        g_client = IOHIDEventSystemClientCreate(kCFAllocatorDefault, 0, 0, NULL, 0);
        tap_log("g_client=%p\n", (void*)g_client);
    });
    pthread_t t;
    pthread_attr_t a;
    pthread_attr_init(&a);
    pthread_attr_setdetachstate(&a, PTHREAD_CREATE_DETACHED);
    pthread_create(&t, &a, sock_thread, NULL);
    pthread_attr_destroy(&a);
}
"""

# tap_client2.c â€” supports "tap x y mode" format
TAP_CLIENT2_C = r"""
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
int main(int argc, char* argv[]) {
    /* argv: tap_client2 <x> <y> <mode>  */
    if (argc < 3) { fprintf(stderr, "usage: tap_client2 x y [mode]\n"); return 1; }
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strlcpy(addr.sun_path, "/tmp/tap_sock", sizeof(addr.sun_path));
    if (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) { perror("connect"); return 1; }
    char buf[128];
    int mode = argc > 3 ? atoi(argv[3]) : 0;
    int n = snprintf(buf, sizeof(buf), "tap %s %s %d", argv[1], argv[2], mode);
    write(fd, buf, n);
    char resp[16] = {0}; read(fd, resp, 15); close(fd);
    printf("%s", resp);
    return (strncmp(resp,"ok",2)==0)?0:1;
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

    sftp = c.open_sftp()
    with sftp.open('/tmp/tap_hook_v3.c', 'w') as f: f.write(DEBUG3_C)
    with sftp.open('/tmp/tap_client2.c', 'w') as f: f.write(TAP_CLIENT2_C)
    sftp.close()

    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -shared -fPIC -framework CoreFoundation -framework IOKit '
        '-o /var/jb/usr/lib/tap_hook.dylib /tmp/tap_hook_v3.c 2>&1"; echo compile:$?',
        'compile v3', timeout=60)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -o /var/jb/usr/bin/tap_client2 /tmp/tap_client2.c && '
        'ldid -S /var/jb/usr/bin/tap_client2 && echo ok"',
        'compile tap_client2')

    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/lib/tap_hook.dylib && echo signed',
        'sign dylib')

    # Respring
    run('echo one | /var/jb/usr/bin/sudo -S -p "" killall -9 SpringBoard', 'respring')
    print('Waiting 8s...')
    time.sleep(8)

    sb_line = run('ps -A | grep SpringBoard | grep -v grep', 'sb pid')
    sb_pid = None
    for line in sb_line.splitlines():
        parts = line.split()
        if parts:
            try: sb_pid = int(parts[0]); break
            except ValueError: pass
    print(f'>>> SpringBoard PID: {sb_pid}')

    if sb_pid:
        run('echo one | /var/jb/usr/bin/sudo -S -p "" rm -f /tmp/tap_hook.log /tmp/tap_sock', 'cleanup')
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {sb_pid} /var/jb/usr/lib/tap_hook.dylib 2>&1', 'inject')
        time.sleep(2)

        run('ls -la /tmp/tap_sock && cat /tmp/tap_hook.log', 'socket + initial log')

        modes = [
            (0, 'raw logical (187,333) index=0 no parent'),
            (1, 'normalized (0.499,0.499) index=0 no parent'),
            (2, 'raw logical (187,333) index=1 no parent'),
            (3, 'raw logical (187,333) index=0 WITH parent'),
            (4, 'new client per call'),
        ]
        for mode, desc in modes:
            print(f'>>> WATCH SCREEN: mode {mode} = {desc} <<<')
            run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
                f'/var/jb/usr/bin/tap_client2 187 333 {mode}; echo exit:$?',
                f'mode {mode}: {desc}')
            time.sleep(0.8)

        run('cat /tmp/tap_hook.log', 'full log after all tests')

    c.close()
finally:
    fwd.terminate()
