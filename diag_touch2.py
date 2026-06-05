"""Test jbctl/sbdidlaunch and try bsexec + opainject dylib injection."""
import subprocess, sys, time, paramiko

HELLO_C = '#include <stdio.h>\nint main(){ printf("hello ok\\n"); return 0; }\n'

# Dylib that listens on a Unix socket and dispatches IOHIDEvents from SpringBoard context
TAP_DYLIB_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <mach/mach_time.h>
#include <CoreFoundation/CoreFoundation.h>

// IOHIDEvent private API
typedef void* IOHIDEventSystemClientRef;
typedef struct __IOHIDEvent* IOHIDEventRef;

extern IOHIDEventSystemClientRef IOHIDEventSystemClientCreate(CFAllocatorRef alloc, int type, int flags, void *p, int n);
extern void IOHIDEventSystemClientDispatchEvent(IOHIDEventSystemClientRef c, IOHIDEventRef e);
extern IOHIDEventRef IOHIDEventCreateDigitizerFingerEvent(
    CFAllocatorRef alloc, uint64_t timestamp,
    uint32_t index, uint32_t identity, uint32_t eventMask,
    double x, double y, double z,
    double tipPressure, double twist,
    uint32_t options, uint32_t buttonMask, uint32_t fingerMask);

#define SOCKET_PATH "/tmp/tap_sock"

static IOHIDEventSystemClientRef g_hidclient = NULL;

static void touch_down(double x, double y) {
    if (!g_hidclient)
        g_hidclient = IOHIDEventSystemClientCreate(kCFAllocatorDefault, 0, 0, NULL, 0);
    uint64_t t = mach_absolute_time();
    // eventMask: touch(1)|range(2) = 3, options: digitizerTouch=1
    IOHIDEventRef e = IOHIDEventCreateDigitizerFingerEvent(
        kCFAllocatorDefault, t, 0, 1, 3, x, y, 0, 1.0, 0, 0, 1, 0);
    if (e) { IOHIDEventSystemClientDispatchEvent(g_hidclient, e); CFRelease(e); }
}

static void touch_up(double x, double y) {
    if (!g_hidclient)
        g_hidclient = IOHIDEventSystemClientCreate(kCFAllocatorDefault, 0, 0, NULL, 0);
    uint64_t t = mach_absolute_time();
    IOHIDEventRef e = IOHIDEventCreateDigitizerFingerEvent(
        kCFAllocatorDefault, t, 0, 1, 3, x, y, 0, 0, 0, 0, 0, 0);
    if (e) { IOHIDEventSystemClientDispatchEvent(g_hidclient, e); CFRelease(e); }
}

static void* socket_thread(void* arg) {
    unlink(SOCKET_PATH);
    int srv = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strcpy(addr.sun_path, SOCKET_PATH);
    bind(srv, (struct sockaddr*)&addr, sizeof(addr));
    chmod(SOCKET_PATH, 0777);
    listen(srv, 5);
    fprintf(stderr, "[tap_hook] listening on %s\n", SOCKET_PATH);

    while (1) {
        int cl = accept(srv, NULL, NULL);
        if (cl < 0) continue;
        char buf[256] = {0};
        int n = read(cl, buf, sizeof(buf)-1);
        if (n > 0) {
            double x, y, x2, y2;
            int steps;
            if (sscanf(buf, "tap %lf %lf", &x, &y) == 2) {
                touch_down(x, y);
                usleep(50000);
                touch_up(x, y);
                write(cl, "ok\n", 3);
                fprintf(stderr, "[tap_hook] tap %.1f,%.1f\n", x, y);
            } else if (sscanf(buf, "swipe %lf %lf %lf %lf %d", &x, &y, &x2, &y2, &steps) >= 4) {
                if (steps <= 0) steps = 20;
                touch_down(x, y);
                for (int i = 1; i <= steps; i++) {
                    usleep(16000);
                    double px = x + (x2-x)*i/steps;
                    double py = y + (y2-y)*i/steps;
                    touch_down(px, py);
                }
                usleep(50000);
                touch_up(x2, y2);
                write(cl, "ok\n", 3);
            }
        }
        close(cl);
    }
    return NULL;
}

__attribute__((constructor))
static void init() {
    pthread_t t;
    pthread_create(&t, NULL, socket_thread, NULL);
    pthread_detach(t);
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
    with sftp.open('/tmp/hello.c', 'w') as f: f.write(HELLO_C)
    with sftp.open('/tmp/tap_hook.c', 'w') as f: f.write(TAP_DYLIB_C)
    sftp.close()

    # 1. jbctl and sbdidlaunch help
    run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/jbctl 2>&1', 'jbctl')
    run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/basebin/sbdidlaunch 2>&1 | head -10', 'sbdidlaunch')

    # 2. Compile hello with no extra flags
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c "clang /tmp/hello.c -o /tmp/hello 2>&1"; echo compile_exit:$?',
        'compile hello (no flags)')

    # 3. Check if binary exists
    run('ls -la /tmp/hello', 'hello binary exists')

    # 4. Try jbctl trust
    run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/jbctl trust /tmp/hello 2>&1; echo exit:$?',
        'jbctl trust hello')

    # 5. Run hello after jbctl trust
    run('echo one | /var/jb/usr/bin/sudo -S -p "" /tmp/hello; echo exit:$?', 'run hello after trust')

    # 6. Try launchctl bsexec with SpringBoard PID
    sb_pid = run('pgrep SpringBoard', 'springboard pid').strip()
    if sb_pid:
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" launchctl bsexec {sb_pid} /tmp/hello; echo exit:$?',
            f'bsexec springboard({sb_pid}) hello')

    # 7. Copy to /var/jb/usr/bin and try running from there
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"cp /tmp/hello /var/jb/usr/bin/hello_test && '
        'ldid -S /var/jb/usr/bin/hello_test && '
        '/var/jb/usr/bin/hello_test; echo exit:$?"',
        'hello from /var/jb/usr/bin/')

    # 8. Compile tap_hook.dylib
    print('=== Compiling tap_hook.dylib ===')
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -shared -fPIC -framework CoreFoundation -framework IOKit '
        '-o /tmp/tap_hook.dylib /tmp/tap_hook.c 2>&1"; echo dylib_exit:$?',
        'compile tap_hook.dylib', timeout=60)

    # 9. Sign dylib and inject into SpringBoard via opainject
    if sb_pid:
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
            f'"ldid -S /tmp/tap_hook.dylib && '
            f'/var/jb/basebin/opainject {sb_pid} /tmp/tap_hook.dylib 2>&1"; echo inject_exit:$?',
            f'opainject into springboard({sb_pid})')

    # 10. Wait a bit then test tap via socket
    time.sleep(2)
    run('ls -la /tmp/tap_sock 2>/dev/null || echo "socket not created"', 'socket file')
    run('echo "tap 187 333" | /var/jb/usr/bin/nc -U /tmp/tap_sock 2>&1; echo nc_exit:$?',
        'test tap via socket', timeout=5)

    c.close()
finally:
    fwd.terminate()
