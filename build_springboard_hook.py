"""Build tap_hook.dylib for SpringBoard injection.
SpringBoard has com.apple.backboardd.pointerAutomation, so
XCSynthesizedEventRecord.synthesizeWithError: works from inside it.
Socket server at /tmp/tap_sock (already proven to work in SpringBoard).
"""
import subprocess, sys, time, paramiko

HOOK_M = r"""
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <pthread.h>
#include <errno.h>
#include <sys/stat.h>
#include <stdarg.h>

#define SOCK_PATH "/tmp/tap_sock"
#define LOG_PATH  "/tmp/taphook.log"

static FILE* g_logf = NULL;
static void tlog(const char* fmt, ...) __attribute__((format(printf,1,2)));
static void tlog(const char* fmt, ...) {
    va_list ap;
    if (g_logf) {
        va_start(ap, fmt);
        vfprintf(g_logf, fmt, ap);
        fputc('\n', g_logf);
        fflush(g_logf);
        va_end(ap);
    }
}

@protocol XCPointerEventPathP <NSObject>
- (instancetype)initForTouchAtPoint:(CGPoint)point offset:(double)offset;
- (void)pressDownAtOffset:(double)offset;
- (void)liftUpAtOffset:(double)offset;
- (void)moveToPoint:(CGPoint)point atOffset:(double)offset;
@end

@protocol XCSynthesizedEventRecordP <NSObject>
- (instancetype)initWithName:(NSString*)name interfaceOrientation:(NSInteger)orientation;
- (void)addPointerEventPath:(id<XCPointerEventPathP>)path;
- (BOOL)synthesizeWithError:(NSError**)error;
@end

static Class g_pathCls;
static Class g_recCls;

static int do_tap(double x, double y) {
    if (!g_pathCls || !g_recCls) { tlog("do_tap: classes nil"); return 1; }
    @autoreleasepool {
        CGPoint pt = CGPointMake(x, y);
        id<XCPointerEventPathP> path = [[(id)g_pathCls alloc] initForTouchAtPoint:pt offset:0.0];
        if (!path) { tlog("do_tap: path nil"); return 1; }
        [path pressDownAtOffset:0.0];
        [path liftUpAtOffset:0.1];
        id<XCSynthesizedEventRecordP> rec = [[(id)g_recCls alloc]
            initWithName:@"Tap" interfaceOrientation:1];
        [rec addPointerEventPath:path];
        NSError* err = nil;
        BOOL ok = [rec synthesizeWithError:&err];
        tlog("do_tap(%.0f,%.0f) ok=%d err=%s", x, y, ok,
            err ? [err.localizedDescription UTF8String] : "nil");
        return ok ? 0 : 1;
    }
}

static int do_swipe(double x1, double y1, double x2, double y2, int steps) {
    if (!g_pathCls || !g_recCls) return 1;
    if (steps < 2) steps = 2;
    @autoreleasepool {
        CGPoint start = CGPointMake(x1, y1);
        id<XCPointerEventPathP> path = [[(id)g_pathCls alloc] initForTouchAtPoint:start offset:0.0];
        if (!path) return 1;
        [path pressDownAtOffset:0.0];
        double dur = 0.4;
        for (int i = 1; i <= steps; i++) {
            double t = (double)i / steps;
            CGPoint mid = CGPointMake(x1 + (x2-x1)*t, y1 + (y2-y1)*t);
            [path moveToPoint:mid atOffset:dur * t];
        }
        [path liftUpAtOffset:dur];
        id<XCSynthesizedEventRecordP> rec = [[(id)g_recCls alloc]
            initWithName:@"Swipe" interfaceOrientation:1];
        [rec addPointerEventPath:path];
        NSError* err = nil;
        BOOL ok = [rec synthesizeWithError:&err];
        NSLog(@"[tap_hook] swipe ok=%d err=%@", ok, err);
        return ok ? 0 : 1;
    }
}

static void* server_thread(void* arg) {
    unlink(SOCK_PATH);
    int srv = socket(AF_UNIX, SOCK_STREAM, 0);
    if (srv < 0) { NSLog(@"[tap_hook] socket failed %d", errno); return NULL; }

    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strlcpy(addr.sun_path, SOCK_PATH, sizeof(addr.sun_path));

    if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        tlog("bind failed %d", errno); close(srv); return NULL;
    }
    chmod(SOCK_PATH, 0777);
    listen(srv, 8);
    tlog("socket ready at %s", SOCK_PATH);

    while (1) {
        int fd = accept(srv, NULL, NULL);
        if (fd < 0) continue;
        char buf[256] = {0};
        ssize_t n = recv(fd, buf, sizeof(buf)-1, 0);
        if (n <= 0) { close(fd); continue; }
        buf[n] = 0;

        int result = 1;
        double x, y, x2, y2;
        int steps;
        if (sscanf(buf, "tap %lf %lf", &x, &y) == 2) {
            result = do_tap(x, y);
        } else if (sscanf(buf, "swipe %lf %lf %lf %lf %d", &x, &y, &x2, &y2, &steps) == 5) {
            result = do_swipe(x, y, x2, y2, steps);
        }

        const char* resp = (result == 0) ? "ok" : "err";
        send(fd, resp, strlen(resp), 0);
        close(fd);
    }
    return NULL;
}

static void load_xc_frameworks(void) {
    const char* fws[] = {
        "/Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport",
        "/Developer/Library/PrivateFrameworks/XCUIAutomation.framework/XCUIAutomation",
        "/Developer/Library/PrivateFrameworks/XCTestCore.framework/XCTestCore",
        NULL
    };
    for (int i = 0; fws[i]; i++) {
        void* h = dlopen(fws[i], RTLD_GLOBAL | RTLD_LAZY);
        NSLog(@"[tap_hook] dlopen %s: %p", strrchr(fws[i],'/')+1, h);
    }
}

__attribute__((constructor))
static void hook_init(void) {
    // Use dispatch_after so dlopen returns immediately to opainject
    dispatch_after(
        dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)),
        dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0),
    ^{
        g_logf = fopen(LOG_PATH, "a");
        tlog("=== hook_init in PID %d ===", getpid());
        load_xc_frameworks();

        g_pathCls = NSClassFromString(@"XCPointerEventPath");
        g_recCls  = NSClassFromString(@"XCSynthesizedEventRecord");
        tlog("XCPointerEventPath=%p XCSynthesizedEventRecord=%p",
            (__bridge void*)g_pathCls, (__bridge void*)g_recCls);

        if (!g_pathCls || !g_recCls) {
            tlog("ERROR: XC classes not found");
            return;
        }

        pthread_t thr;
        pthread_create(&thr, NULL, server_thread, NULL);
        pthread_detach(thr);
        tlog("server thread launched");
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
    with sftp.open('/tmp/tap_hook_sb.m', 'w') as f: f.write(HOOK_M)
    sftp.close()

    # Compile as dylib
    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/clang -x objective-c -fobjc-arc '
        '-isysroot /var/jb/usr/share/SDKs/iPhoneOS.sdk '
        '-dynamiclib '
        '-framework Foundation '
        '-framework CoreGraphics '
        '-Wl,-undefined,dynamic_lookup '
        '-o /var/jb/usr/lib/tap_hook.dylib /tmp/tap_hook_sb.m 2>&1',
        'compile tap_hook.dylib', timeout=90)

    out = run('ls -la /var/jb/usr/lib/tap_hook.dylib 2>&1', 'check dylib')
    if 'No such file' in out:
        print('COMPILATION FAILED'); c.close(); exit(1)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" ldid -S /var/jb/usr/lib/tap_hook.dylib; echo signed:$?', 'sign dylib')

    # Get SpringBoard PID
    pid_out = run('ps -A | grep SpringBoard | grep -v grep', 'SpringBoard pid')
    sb_pid = None
    for line in pid_out.splitlines():
        parts = line.split()
        if parts:
            try: sb_pid = int(parts[0]); break
            except ValueError: pass
    print(f'SpringBoard PID: {sb_pid}')

    # Rebuild tap_client to use /tmp/tap_sock
    tap_client_c = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>
int main(int argc, char* argv[]) {
    if (argc < 2) return 1;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un addr; memset(&addr,0,sizeof(addr));
    addr.sun_family = AF_UNIX;
    strlcpy(addr.sun_path, "/tmp/tap_sock", sizeof(addr.sun_path));
    if (connect(fd,(struct sockaddr*)&addr,sizeof(addr))<0){perror("connect");close(fd);return 1;}
    char buf[256]; int n=0;
    if (!strcmp(argv[1],"tap")&&argc>=4)
        n=snprintf(buf,sizeof(buf),"tap %s %s",argv[2],argv[3]);
    else if (!strcmp(argv[1],"swipe")&&argc>=6){
        const char* s=argc>=7?argv[6]:"20";
        n=snprintf(buf,sizeof(buf),"swipe %s %s %s %s %s",argv[2],argv[3],argv[4],argv[5],s);
    } else { close(fd); return 1; }
    write(fd,buf,n);
    char resp[16]={0}; read(fd,resp,15); close(fd);
    printf("%s",resp);
    return strncmp(resp,"ok",2)==0?0:1;
}
"""
    sftp2 = c.open_sftp()
    with sftp2.open('/tmp/tap_client_new.c', 'w') as f: f.write(tap_client_c)
    sftp2.close()
    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/clang -isysroot /var/jb/usr/share/SDKs/iPhoneOS.sdk '
        '-o /var/jb/usr/bin/tap_client /tmp/tap_client_new.c 2>&1 && '
        'ldid -S /var/jb/usr/bin/tap_client && echo "tap_client rebuilt"',
        'rebuild tap_client', timeout=60)

    if sb_pid:
        # Respring to unload any cached old dylib and get a fresh SpringBoard
        run('echo one | /var/jb/usr/bin/sudo -S -p "" rm -f /tmp/tap_sock', 'clean socket')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" killall -9 SpringBoard 2>&1; echo respringed', 'respring')
        print('Waiting 10s for SpringBoard to restart...')
        time.sleep(10)
        pid_out2 = run('ps -A | grep SpringBoard | grep -v grep', 'new SpringBoard pid')
        sb_pid = None
        for line in pid_out2.splitlines():
            parts = line.split()
            if parts:
                try: sb_pid = int(parts[0]); break
                except ValueError: pass
        print(f'New SpringBoard PID: {sb_pid}')
        if not sb_pid:
            print('ERROR: SpringBoard not running after respring'); c.close(); exit(1)

        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {sb_pid} /var/jb/usr/lib/tap_hook.dylib 2>&1',
            f'inject into SpringBoard({sb_pid})')
        time.sleep(3)

        run('ls -la /tmp/tap_sock 2>&1', 'check socket created')
        run('ps -A | grep SpringBoard | grep -v grep', 'SpringBoard still alive?')

        # Ensure tap_client uses /tmp/tap_sock (check it's compiled with old path)
        print('>>> WATCH YOUR SCREEN - should tap center <<<')
        run('/var/jb/usr/bin/tap_client tap 187 333 2>&1; echo exit:$?', 'tap test', timeout=8)
        time.sleep(1)
        print('>>> WATCH YOUR SCREEN - should swipe up <<<')
        run('/var/jb/usr/bin/tap_client swipe 187 500 187 200 20 2>&1; echo exit:$?', 'swipe test', timeout=10)
    else:
        print('ERROR: SpringBoard PID not found')

    c.close()
finally:
    fwd.terminate()
