"""Build + inject a tap-hook dylib into testmanagerd.
testmanagerd has com.apple.backboardd.pointerAutomation, so
XCSynthesizedEventRecord.synthesizeWithError: works from inside it.
"""
import subprocess, sys, time, paramiko

HOOK_M = r"""
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <dlfcn.h>

@protocol XCPointerEventPathP <NSObject>
- (instancetype)initForTouchAtPoint:(CGPoint)point offset:(double)offset;
- (void)pressDownAtOffset:(double)offset;
- (void)liftUpAtOffset:(double)offset;
@end

@protocol XCSynthesizedEventRecordP <NSObject>
- (instancetype)initWithName:(NSString*)name interfaceOrientation:(NSInteger)orientation;
- (void)addPointerEventPath:(id<XCPointerEventPathP>)path;
- (BOOL)synthesizeWithError:(NSError**)error;
@end

__attribute__((constructor))
static void hook_autotap(void) {
    // Return immediately from constructor â€” schedule work on background queue
    // so dlopen returns to opainject without blocking.
    dispatch_after(
        dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.5 * NSEC_PER_SEC)),
        dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0),
    ^{
        NSLog(@"[tap_hook] auto-tap starting in PID %d", getpid());

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

        @autoreleasepool {
            Class pathCls = NSClassFromString(@"XCPointerEventPath");
            Class recCls  = NSClassFromString(@"XCSynthesizedEventRecord");
            NSLog(@"[tap_hook] path=%p rec=%p",
                (__bridge void*)pathCls, (__bridge void*)recCls);

            if (!pathCls || !recCls) {
                NSLog(@"[tap_hook] classes missing"); return;
            }

            CGPoint pt = CGPointMake(187.0, 333.0);
            id<XCPointerEventPathP> path = [[(id)pathCls alloc] initForTouchAtPoint:pt offset:0.0];
            [path pressDownAtOffset:0.0];
            [path liftUpAtOffset:0.1];

            id<XCSynthesizedEventRecordP> rec = [[(id)recCls alloc]
                initWithName:@"AutoTap" interfaceOrientation:1];
            [rec addPointerEventPath:path];

            NSError* err = nil;
            BOOL ok = [rec synthesizeWithError:&err];
            NSLog(@"[tap_hook] synthesize=%d err=%@", ok, err);
        }
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
        if e: print('  err:', e[:600])
        print()
        return o

    sftp = c.open_sftp()
    with sftp.open('/tmp/tap_synth_hook.m', 'w') as f: f.write(HOOK_M)
    sftp.close()

    # Compile as dylib
    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/clang -x objective-c -fobjc-arc '
        '-isysroot /var/jb/usr/share/SDKs/iPhoneOS.sdk '
        '-dynamiclib '
        '-framework Foundation '
        '-framework CoreGraphics '
        '-Wl,-undefined,dynamic_lookup '
        '-o /var/jb/usr/lib/tap_synth_hook.dylib /tmp/tap_synth_hook.m 2>&1',
        'compile dylib', timeout=90)

    out = run('ls -la /var/jb/usr/lib/tap_synth_hook.dylib 2>&1', 'check dylib')
    if 'No such file' in out:
        print('COMPILATION FAILED')
        c.close()
        exit(1)

    # Sign
    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        'ldid -S /var/jb/usr/lib/tap_synth_hook.dylib 2>&1; echo signed:$?',
        'sign dylib')

    # Get testmanagerd PID
    pid_out = run('ps -A | grep testmanagerd | grep -v grep', 'testmanagerd pid')
    tm_pid = None
    for line in pid_out.splitlines():
        parts = line.split()
        if parts:
            try: tm_pid = int(parts[0]); break
            except ValueError: pass
    print(f'testmanagerd PID: {tm_pid}')

    if not tm_pid:
        # Start testmanagerd
        run('echo one | /var/jb/usr/bin/sudo -S -p "" '
            'launchctl start com.apple.testmanagerd 2>&1; sleep 2',
            'start testmanagerd')
        pid_out = run('ps -A | grep testmanagerd | grep -v grep', 'testmanagerd pid 2')
        for line in pid_out.splitlines():
            parts = line.split()
            if parts:
                try: tm_pid = int(parts[0]); break
                except ValueError: pass
        print(f'testmanagerd PID (after start): {tm_pid}')

    if tm_pid:
        # Restart testmanagerd for a fresh process
        run('echo one | /var/jb/usr/bin/sudo -S -p "" launchctl stop com.apple.testmanagerd 2>&1; sleep 1', 'stop testmanagerd')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" launchctl start com.apple.testmanagerd 2>&1; sleep 2', 'restart testmanagerd')
        pid_out2 = run('ps -A | grep testmanagerd | grep -v grep', 'new testmanagerd pid')
        for line in pid_out2.splitlines():
            parts = line.split()
            if parts:
                try: tm_pid = int(parts[0]); break
                except ValueError: pass
        print(f'Fresh testmanagerd PID: {tm_pid}')

        print('>>> WATCH SCREEN - should AUTO-TAP at center 2 seconds after inject <<<')
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {tm_pid} /var/jb/usr/lib/tap_synth_hook.dylib 2>&1',
            f'inject auto-tap into testmanagerd({tm_pid})')

        time.sleep(5)  # wait for sleep(2) + synthesis

        # Read NSLog output via syslog/log
        run('echo one | /var/jb/usr/bin/sudo -S -p "" '
            'log show --last 20s 2>/dev/null | grep -i "tap_hook" | tail -20 || '
            'syslog 2>/dev/null | grep tap_hook | tail -20 || '
            'journalctl 2>/dev/null | grep tap_hook | tail -20 || '
            'echo "(no log reader available)"',
            'NSLog output')

        run('ps -A | grep testmanagerd | grep -v grep', 'testmanagerd still alive?')
    else:
        print('ERROR: no testmanagerd PID')

    c.close()
finally:
    fwd.terminate()
