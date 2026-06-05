"""Compile ObjC tap tool on-device using XCSynthesizedEventRecord."""
import subprocess, sys, time, paramiko

TAP_SYNTH_M = r"""
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <dispatch/dispatch.h>

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

@protocol XCTRunnerDaemonSessionP <NSObject>
+ (instancetype)sharedSession;
- (void)synthesizeEvent:(id<XCSynthesizedEventRecordP>)event completion:(void(^)(NSError*))completion;
@end

static void load_frameworks(void) {
    const char* fws[] = {
        "/Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport",
        "/Developer/Library/PrivateFrameworks/XCUIAutomation.framework/XCUIAutomation",
        "/Developer/Library/PrivateFrameworks/XCTestCore.framework/XCTestCore",
        NULL
    };
    for (int i = 0; fws[i]; i++) {
        dlopen(fws[i], RTLD_GLOBAL | RTLD_NOW);
    }
}

static int synthesize_record(id<XCSynthesizedEventRecordP> record) {
    // First: try synthesizeWithError: directly (needs com.apple.backboardd.pointerAutomation)
    NSError* directErr = nil;
    BOOL ok = [record synthesizeWithError:&directErr];
    if (ok) { return 0; }
    fprintf(stderr, "synthesizeWithError: %s\n",
        directErr ? [directErr.localizedDescription UTF8String] : "nil error");

    // Fallback: route through XCTRunnerDaemonSession (needs testmanagerd running)
    Class runCls = NSClassFromString(@"XCTRunnerDaemonSession");
    if (!runCls) { fprintf(stderr, "XCTRunnerDaemonSession not found\n"); return 1; }

    // Try to initiate a fresh session
    id<XCTRunnerDaemonSessionP> session = nil;
    dispatch_semaphore_t initSem = dispatch_semaphore_create(0);
    __block id initedSession = nil;
    SEL initiateSel = NSSelectorFromString(@"initiateSharedSessionWithCompletion:");
    if ([runCls respondsToSelector:initiateSel]) {
        void (*initiateIMP)(id, SEL, void(^)(id, NSError*)) =
            (void(*)(id, SEL, void(^)(id,NSError*)))[runCls methodForSelector:initiateSel];
        initiateIMP(runCls, initiateSel, ^(id s, NSError* e) {
            initedSession = e ? nil : s;
            dispatch_semaphore_signal(initSem);
        });
        dispatch_semaphore_wait(initSem,
            dispatch_time(DISPATCH_TIME_NOW, 5LL * NSEC_PER_SEC));
        session = initedSession;
    }
    if (!session) {
        session = [(id<XCTRunnerDaemonSessionP>)runCls sharedSession];
    }
    if (!session) { fprintf(stderr, "sharedSession nil\n"); return 1; }

    dispatch_semaphore_t sem = dispatch_semaphore_create(0);
    __block NSError* berr = nil;
    [session synthesizeEvent:record completion:^(NSError* e) {
        berr = e;
        dispatch_semaphore_signal(sem);
    }];
    long waited = dispatch_semaphore_wait(sem,
        dispatch_time(DISPATCH_TIME_NOW, 5LL * NSEC_PER_SEC));
    if (waited) { fprintf(stderr, "synthesizeEvent timed out\n"); return 1; }
    if (berr) {
        fprintf(stderr, "synthesizeEvent failed: %s\n",
            [berr.localizedDescription UTF8String]);
        return 1;
    }
    return 0;
}

int main(int argc, char* argv[]) {
    @autoreleasepool {
        load_frameworks();

        Class pathCls = NSClassFromString(@"XCPointerEventPath");
        Class recCls  = NSClassFromString(@"XCSynthesizedEventRecord");
        if (!pathCls || !recCls) {
            fprintf(stderr, "ERROR: XC classes not loaded\n");
            return 1;
        }

        if (argc < 2) {
            fprintf(stderr, "Usage: xc_tap tap X Y | swipe X1 Y1 X2 Y2 [STEPS]\n");
            return 1;
        }

        id<XCPointerEventPathP> path = nil;
        NSString* recName = @"Tap";

        if (strcmp(argv[1], "tap") == 0 && argc >= 4) {
            double x = atof(argv[2]), y = atof(argv[3]);
            CGPoint pt = CGPointMake(x, y);
            path = [[(id)pathCls alloc] initForTouchAtPoint:pt offset:0.0];
            [path pressDownAtOffset:0.0];
            [path liftUpAtOffset:0.1];

        } else if (strcmp(argv[1], "swipe") == 0 && argc >= 6) {
            double x1 = atof(argv[2]), y1 = atof(argv[3]);
            double x2 = atof(argv[4]), y2 = atof(argv[5]);
            int steps = (argc >= 7) ? atoi(argv[6]) : 20;
            if (steps < 2) steps = 2;
            recName = @"Swipe";

            CGPoint start = CGPointMake(x1, y1);
            path = [[(id)pathCls alloc] initForTouchAtPoint:start offset:0.0];
            [path pressDownAtOffset:0.0];

            double duration = 0.4;
            for (int i = 1; i <= steps; i++) {
                double t = (double)i / steps;
                CGPoint mid = CGPointMake(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t);
                [path moveToPoint:mid atOffset:duration * t];
            }
            [path liftUpAtOffset:duration];

        } else {
            fprintf(stderr, "Usage: xc_tap tap X Y | swipe X1 Y1 X2 Y2 [STEPS]\n");
            return 1;
        }

        if (!path) { fprintf(stderr, "ERROR: path creation failed\n"); return 1; }

        id<XCSynthesizedEventRecordP> record = [[(id)recCls alloc]
            initWithName:recName interfaceOrientation:1];
        [record addPointerEventPath:path];

        int result = synthesize_record(record);
        if (result == 0) {
            printf("ok\n");
        }
        return result;
    }
}
"""

ENTITLEMENTS_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>platform-application</key>
    <true/>
    <key>com.apple.private.skip-library-validation</key>
    <true/>
    <key>com.apple.security.get-task-allow</key>
    <true/>
    <key>com.apple.springboard.remote-run-tests</key>
    <true/>
    <key>com.apple.private.testmanagerd.client</key>
    <true/>
    <key>com.apple.backboardd.pointerAutomation</key>
    <true/>
    <key>com.apple.backboardd.pointerRepositioning</key>
    <true/>
    <key>com.apple.backboardd.setDeviceOrientation</key>
    <true/>
    <key>com.apple.private.dt.automationmode.writer-client</key>
    <true/>
    <key>com.apple.frontboard.debugapplications</key>
    <true/>
    <key>com.apple.frontboard.launchapplications</key>
    <true/>
    <key>com.apple.accessibility.api</key>
    <true/>
</dict>
</plist>
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
    with sftp.open('/tmp/tap_synth.m', 'w') as f: f.write(TAP_SYNTH_M)
    with sftp.open('/tmp/ent.plist', 'w') as f: f.write(ENTITLEMENTS_PLIST)
    sftp.close()

    run('echo one | /var/jb/usr/bin/sudo -S -p "" rm -f /var/jb/usr/bin/xc_tap', 'remove old binary')

    compile_cmd = (
        'echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/clang -x objective-c -fobjc-arc '
        '-isysroot /var/jb/usr/share/SDKs/iPhoneOS.sdk '
        '-framework Foundation '
        '-framework CoreGraphics '
        '-framework UIKit '
        '-Wl,-undefined,dynamic_lookup '
        '-o /var/jb/usr/bin/xc_tap /tmp/tap_synth.m 2>&1'
    )
    run(compile_cmd, 'compile xc_tap', timeout=90)

    binary_check = run('ls -la /var/jb/usr/bin/xc_tap 2>&1', 'check binary')
    if 'No such file' not in binary_check:
        run('echo one | /var/jb/usr/bin/sudo -S -p "" '
            'ldid -S/tmp/ent.plist /var/jb/usr/bin/xc_tap 2>&1; echo signed:$?',
            'sign with ldid')

        print('>>> WATCH YOUR SCREEN - should tap center of screen <<<')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/xc_tap tap 187 333 2>&1; echo exit:$?',
            'xc_tap tap test', timeout=10)
        time.sleep(1)
        print('>>> WATCH YOUR SCREEN - should swipe up <<<')
        run('echo one | /var/jb/usr/bin/sudo -S -p "" /var/jb/usr/bin/xc_tap swipe 187 500 187 200 20 2>&1; echo exit:$?',
            'xc_tap swipe test', timeout=10)
    else:
        print('Compilation failed')

    c.close()
finally:
    fwd.terminate()
