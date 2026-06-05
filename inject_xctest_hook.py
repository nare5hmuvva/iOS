"""
Inject an ObjC dylib into SpringBoard that uses XCEventGenerator
(from the DDI's XCTAutomationSupport.framework) for reliable touch injection.
XCEventGenerator talks to testmanagerd â€” Apple's own automation channel.
No HID entitlement needed.
"""
import subprocess, sys, time, paramiko

XCTEST_HOOK_M = r"""
/* Objective-C dylib â€” compile as .m */
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <dlfcn.h>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>

#define SOCK_FILE "/tmp/tap_sock"
#define LOG_FILE  "/tmp/taphook.log"

/* â”€â”€ forward declarations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
@interface XCEventGenerator : NSObject
+ (instancetype)sharedGenerator;
- (void)tapAtTouchPoint:(CGPoint)pt
            orientation:(NSInteger)orientation
                handler:(void (^)(NSError *))handler;
- (void)pressAtPoint:(CGPoint)pt
         forDuration:(double)duration
         orientation:(NSInteger)orientation
             handler:(void (^)(NSError *))handler;
- (void)dragFromPoint:(CGPoint)start
              toPoint:(CGPoint)end
             duration:(double)dur
          orientation:(NSInteger)orientation
              handler:(void (^)(NSError *))handler;
@end

/* â”€â”€ logging â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
static void tlog(NSString *msg) {
    FILE *f = fopen(LOG_FILE, "a");
    if (f) { fprintf(f, "%s\n", [msg UTF8String]); fclose(f); }
}

/* â”€â”€ one-time XCEventGenerator setup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
static XCEventGenerator *g_gen = nil;

static void ensure_generator(void) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        const char *path =
            "/Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport";
        void *h = dlopen(path, RTLD_NOW | RTLD_GLOBAL);
        tlog([NSString stringWithFormat:@"dlopen XCTAutomationSupport: %p (%s)",
              h, h ? "ok" : dlerror()]);
        Class cls = NSClassFromString(@"XCEventGenerator");
        tlog([NSString stringWithFormat:@"XCEventGenerator class: %@", cls]);
        if (cls) {
            g_gen = [cls sharedGenerator];
            tlog([NSString stringWithFormat:@"sharedGenerator: %@", g_gen]);
        }
    });
}

/* â”€â”€ socket server â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
static void* server_thread(void *_) {
    unlink(SOCK_FILE);
    int srv = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, SOCK_FILE, sizeof(addr.sun_path)-1);
    bind(srv, (struct sockaddr*)&addr, sizeof(addr));
    chmod(SOCK_FILE, 0666);
    listen(srv, 8);
    tlog(@"server ready");

    while (1) {
        int cl = accept(srv, NULL, NULL);
        if (cl < 0) continue;
        char buf[256] = {0};
        read(cl, buf, sizeof(buf)-1);
        tlog([NSString stringWithFormat:@"cmd: %s", buf]);

        double x = 0, y = 0, x2 = 0, y2 = 0, dur = 0.3;
        BOOL handled = NO;

        if (sscanf(buf, "tap %lf %lf", &x, &y) == 2) {
            CGPoint pt = CGPointMake(x, y);
            __block BOOL done = NO;
            dispatch_async(dispatch_get_main_queue(), ^{
                ensure_generator();
                if (g_gen && [g_gen respondsToSelector:
                              @selector(tapAtTouchPoint:orientation:handler:)]) {
                    [g_gen tapAtTouchPoint:pt orientation:1 handler:^(NSError *e) {
                        tlog([NSString stringWithFormat:@"tap done err=%@", e]);
                        done = YES;
                    }];
                } else {
                    tlog(@"tapAtTouchPoint not available");
                    done = YES;
                }
            });
            /* spin-wait up to 3 seconds for callback */
            for (int i = 0; i < 300 && !done; i++) usleep(10000);
            write(cl, done ? "ok\n" : "timeout\n", done ? 3 : 8);
            handled = YES;
        }
        else if (sscanf(buf, "swipe %lf %lf %lf %lf %lf", &x, &y, &x2, &y2, &dur) >= 4) {
            CGPoint from = CGPointMake(x, y), to = CGPointMake(x2, y2);
            __block BOOL done = NO;
            dispatch_async(dispatch_get_main_queue(), ^{
                ensure_generator();
                if (g_gen && [g_gen respondsToSelector:
                              @selector(dragFromPoint:toPoint:duration:orientation:handler:)]) {
                    [g_gen dragFromPoint:from toPoint:to duration:dur
                            orientation:1 handler:^(NSError *e) {
                        tlog([NSString stringWithFormat:@"swipe done err=%@", e]);
                        done = YES;
                    }];
                } else {
                    tlog(@"dragFromPoint not available");
                    done = YES;
                }
            });
            for (int i = 0; i < 500 && !done; i++) usleep(10000);
            write(cl, done ? "ok\n" : "timeout\n", done ? 3 : 8);
            handled = YES;
        }

        if (!handled) write(cl, "err\n", 4);
        close(cl);
    }
    return NULL;
}

/* â”€â”€ constructor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */
__attribute__((constructor))
static void hook_init(void) {
    tlog(@"=== xctest_hook loaded ===");
    /* pre-warm generator on main queue */
    dispatch_async(dispatch_get_main_queue(), ^{
        ensure_generator();
    });
    pthread_t t;
    pthread_attr_t a;
    pthread_attr_init(&a);
    pthread_attr_setdetachstate(&a, PTHREAD_CREATE_DETACHED);
    pthread_create(&t, &a, server_thread, NULL);
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
    with sftp.open('/tmp/tap_xctest_hook.m', 'w') as f: f.write(XCTEST_HOOK_M)
    sftp.close()

    # Compile as ObjC
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -fobjc-arc -shared -fPIC '
        '-framework CoreFoundation -framework Foundation -framework CoreGraphics '
        '-x objective-c '
        '-o /var/jb/usr/lib/tap_hook.dylib /tmp/tap_xctest_hook.m 2>&1"; echo compile:$?',
        'compile xctest hook', timeout=60)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/lib/tap_hook.dylib && echo signed',
        'sign')

    # Respring + inject
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
        run('echo one | /var/jb/usr/bin/sudo -S -p "" rm -f /tmp/taphook.log /tmp/tap_sock', 'clean')
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {sb_pid} /var/jb/usr/lib/tap_hook.dylib 2>&1', 'inject')
        time.sleep(2)

        run('ls /tmp/tap_sock && cat /tmp/taphook.log', 'socket + init log')

        print('=== WATCH YOUR SCREEN â€” tap center ===')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" '
            '/var/jb/usr/bin/tap_client tap 187 333; echo exit:$?', 'tap center', timeout=15)
        time.sleep(0.5)
        run('cat /tmp/taphook.log', 'log after tap')

        print('=== WATCH YOUR SCREEN â€” swipe up ===')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" '
            '/var/jb/usr/bin/tap_client swipe 187 600 187 150; echo exit:$?', 'swipe up', timeout=15)
        time.sleep(0.5)
        run('cat /tmp/taphook.log', 'final log')

    c.close()
finally:
    fwd.terminate()
