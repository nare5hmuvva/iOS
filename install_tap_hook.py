"""
Compile tap_hook.dylib, inject into SpringBoard via opainject.
The dylib listens on /tmp/tap_sock for tap/swipe commands and dispatches
IOHIDEvents from within SpringBoard's GUI bootstrap context.
Also installs tap_client (tiny socket sender) at /var/jb/usr/bin/tap_client.
"""
import subprocess, sys, time, paramiko

# â”€â”€ tap_hook.dylib â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
TAP_HOOK_C = r"""
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

/* Private IOHIDEvent API */
typedef void*  IOHIDEventSystemClientRef;
typedef struct __IOHIDEvent* IOHIDEventRef;

/* kIOHIDDigitizerEventRange=1, kIOHIDDigitizerEventTouch=2 */
#define DIGI_RANGE_TOUCH 3

extern IOHIDEventSystemClientRef IOHIDEventSystemClientCreate(
    CFAllocatorRef alloc, int type, int flags, void *p, int n);
extern void IOHIDEventSystemClientDispatchEvent(
    IOHIDEventSystemClientRef c, IOHIDEventRef e);

/* 13-param signature confirmed for iOS 15:
   alloc, time, index, identity, eventMask,
   x, y, z, tipPressure, twist,
   range(bool), touch(bool), options */
extern IOHIDEventRef IOHIDEventCreateDigitizerFingerEvent(
    CFAllocatorRef alloc, uint64_t ts,
    uint32_t index, uint32_t identity, uint32_t eventMask,
    double x, double y, double z,
    double tipPressure, double twist,
    int range, int touch, uint32_t options);

#define SOCK_PATH "/tmp/tap_sock"

static IOHIDEventSystemClientRef g_client = NULL;

static void send_finger(double x, double y, int down) {
    if (!g_client)
        g_client = IOHIDEventSystemClientCreate(kCFAllocatorDefault, 0, 0, NULL, 0);

    uint64_t t = mach_absolute_time();
    IOHIDEventRef e = IOHIDEventCreateDigitizerFingerEvent(
        kCFAllocatorDefault, t,
        0, 1,           /* index=0, identity=1 */
        DIGI_RANGE_TOUCH,
        x, y, 0,
        down ? 1.0 : 0.0, 0,
        down, down,     /* range, touch â€” was always 0 before (bug) */
        0);
    if (e) {
        IOHIDEventSystemClientDispatchEvent(g_client, e);
        CFRelease(e);
    }
}

static void do_tap(double x, double y) {
    send_finger(x, y, 1);
    usleep(80000);
    send_finger(x, y, 0);
}

static void do_swipe(double x1, double y1, double x2, double y2, int steps) {
    if (steps < 5) steps = 20;
    send_finger(x1, y1, 1);
    for (int i = 1; i <= steps; i++) {
        usleep(16000);
        send_finger(x1 + (x2-x1)*i/steps, y1 + (y2-y1)*i/steps, 1);
    }
    usleep(30000);
    send_finger(x2, y2, 0);
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
    fprintf(stderr, "[tap_hook] ready at %s\n", SOCK_PATH);

    while (1) {
        int cl = accept(srv, NULL, NULL);
        if (cl < 0) continue;
        char buf[256] = {0};
        int n = (int)read(cl, buf, sizeof(buf)-1);
        if (n > 0) {
            double x, y, x2, y2; int steps = 20;
            if (strncmp(buf, "tap", 3) == 0 &&
                sscanf(buf+3, " %lf %lf", &x, &y) == 2) {
                do_tap(x, y);
                write(cl, "ok\n", 3);
            } else if (strncmp(buf, "swipe", 5) == 0 &&
                       sscanf(buf+5, " %lf %lf %lf %lf %d",
                              &x, &y, &x2, &y2, &steps) >= 4) {
                do_swipe(x, y, x2, y2, steps);
                write(cl, "ok\n", 3);
            } else {
                write(cl, "err\n", 4);
            }
        }
        close(cl);
    }
    return NULL;
}

__attribute__((constructor))
static void tap_hook_init(void) {
    pthread_t t;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    pthread_create(&t, &attr, sock_thread, NULL);
    pthread_attr_destroy(&attr);
}
"""

# â”€â”€ tap_client.c â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
TAP_CLIENT_C = r"""
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>

int main(int argc, char* argv[]) {
    if (argc < 2) {
        fprintf(stderr, "usage: tap_client tap <x> <y>\n"
                        "       tap_client swipe <x1> <y1> <x2> <y2>\n");
        return 1;
    }
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strlcpy(addr.sun_path, "/tmp/tap_sock", sizeof(addr.sun_path));
    if (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("connect");
        return 1;
    }
    char buf[256];
    int n;
    if (strcmp(argv[1], "tap") == 0 && argc >= 4) {
        n = snprintf(buf, sizeof(buf), "tap %s %s", argv[2], argv[3]);
    } else if (strcmp(argv[1], "swipe") == 0 && argc >= 6) {
        n = snprintf(buf, sizeof(buf), "swipe %s %s %s %s", argv[2], argv[3], argv[4], argv[5]);
    } else {
        fprintf(stderr, "bad command\n"); return 1;
    }
    write(fd, buf, n);
    char resp[16] = {0};
    read(fd, resp, sizeof(resp)-1);
    close(fd);
    printf("%s", resp);
    return (strncmp(resp, "ok", 2) == 0) ? 0 : 1;
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

    # Upload sources
    sftp = c.open_sftp()
    with sftp.open('/tmp/tap_hook2.c', 'w') as f:   f.write(TAP_HOOK_C)
    with sftp.open('/tmp/tap_client.c', 'w') as f:  f.write(TAP_CLIENT_C)
    sftp.close()

    # Get SpringBoard PID
    sb_line = run('ps -A | grep SpringBoard | grep -v grep', 'springboard pid')
    sb_pid = None
    for line in sb_line.splitlines():
        parts = line.split()
        if parts:
            try:
                sb_pid = int(parts[0]); break
            except ValueError: pass
    print(f'>>> SpringBoard PID: {sb_pid}')

    # Compile dylib into /var/jb/usr/lib/ (trusted path)
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -shared -fPIC -framework CoreFoundation '
        '-o /var/jb/usr/lib/tap_hook.dylib /tmp/tap_hook2.c 2>&1"; echo compile:$?',
        'compile tap_hook.dylib', timeout=60)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/lib/tap_hook.dylib && echo signed',
        'sign tap_hook.dylib')

    # Compile tap_client
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -o /var/jb/usr/bin/tap_client /tmp/tap_client.c 2>&1"; echo compile:$?',
        'compile tap_client', timeout=60)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/bin/tap_client && echo signed',
        'sign tap_client')

    # Inject into SpringBoard
    if sb_pid:
        out = run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
                  f'/var/jb/basebin/opainject {sb_pid} /var/jb/usr/lib/tap_hook.dylib 2>&1',
                  f'opainject into SpringBoard({sb_pid})')

        time.sleep(2)

        # Check if socket appeared
        run('ls -la /tmp/tap_sock 2>/dev/null || echo "no socket yet"', 'socket check')

        # Test via tap_client (which connects to the socket)
        print('>>> WATCH YOUR DEVICE SCREEN <<<')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/tap_client tap 187 333; echo exit:$?',
            'tap center via tap_client')

        time.sleep(1)

        print('>>> SWIPE UP <<<')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/tap_client swipe 187 600 187 150; echo exit:$?',
            'swipe up via tap_client')

    c.close()
finally:
    fwd.terminate()
