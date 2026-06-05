"""
Build working tap binary at /var/jb/usr/bin/tap using XCEventGenerator,
AND inject tap_hook.dylib into SpringBoard via opainject as a fallback.
"""
import subprocess, sys, time, paramiko

TAP_ENTITLEMENTS = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>get-task-allow</key><true/>
    <key>platform-application</key><true/>
    <key>com.apple.private.hid.manager.client</key><true/>
    <key>com.apple.hid.manager.user-access-service</key><true/>
    <key>com.apple.private.security.no-sandbox</key><true/>
</dict></plist>"""

# XCEventGenerator tap binary - uses XCTAutomationSupport from DDI
TAP_XCTEST_M = r"""
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <dlfcn.h>
#include <stdio.h>

// Load XCTAutomationSupport dynamically from the Developer disk image
typedef id (*XCEGSharedGenerator_t)(id cls, SEL sel);

int main(int argc, char* argv[]) {
    if (argc < 3) {
        fprintf(stderr, "usage: tap <x> <y>\n       swipe <x1> <y1> <x2> <y2> [steps]\n");
        return 1;
    }

    // Try to load XCTAutomationSupport from DDI
    const char* paths[] = {
        "/Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport",
        "/Developer/usr/lib/libXCTestBundleInject.dylib",
        NULL
    };
    void* handle = NULL;
    for (int i = 0; paths[i]; i++) {
        handle = dlopen(paths[i], RTLD_NOW);
        if (handle) { fprintf(stderr, "loaded: %s\n", paths[i]); break; }
    }
    if (!handle) {
        fprintf(stderr, "failed to load XCTAutomationSupport: %s\n", dlerror());
        return 1;
    }

    // Get XCEventGenerator class
    Class XCEventGeneratorClass = NSClassFromString(@"XCEventGenerator");
    if (!XCEventGeneratorClass) {
        fprintf(stderr, "XCEventGenerator not found\n");
        return 1;
    }

    id gen = [XCEventGeneratorClass performSelector:@selector(sharedGenerator)];
    if (!gen) {
        fprintf(stderr, "sharedGenerator returned nil\n");
        return 1;
    }

    NSString* cmd = [NSString stringWithUTF8String:argv[1]];

    if ([cmd isEqualToString:@"tap"]) {
        double x = atof(argv[2]), y = atof(argv[3]);
        CGPoint pt = CGPointMake(x, y);
        __block BOOL done = NO;
        __block NSError* tapErr = nil;

        // -tapAtTouchPoint:orientation:handler:
        SEL tapSel = NSSelectorFromString(@"tapAtTouchPoint:orientation:handler:");
        if ([gen respondsToSelector:tapSel]) {
            // Use NSInvocation for the block argument
            NSMethodSignature* sig = [gen methodSignatureForSelector:tapSel];
            NSInvocation* inv = [NSInvocation invocationWithMethodSignature:sig];
            [inv setSelector:tapSel];
            [inv setTarget:gen];
            [inv setArgument:&pt atIndex:2];
            UIDeviceOrientation orient = UIDeviceOrientationPortrait; // 1
            [inv setArgument:&orient atIndex:3];
            void (^handler)(NSError*) = ^(NSError* err) {
                tapErr = err; done = YES;
            };
            [inv setArgument:&handler atIndex:4];
            [inv invoke];
        } else {
            // Fallback: -synthesizeTouchAtPoint:orientation:
            SEL synthSel = NSSelectorFromString(@"synthesizeTouchAtPoint:orientation:");
            if ([gen respondsToSelector:synthSel]) {
                NSInvocation* inv = [NSInvocation invocationWithMethodSignature:
                    [gen methodSignatureForSelector:synthSel]];
                [inv setSelector:synthSel];
                [inv setTarget:gen];
                [inv setArgument:&pt atIndex:2];
                int orient = 1;
                [inv setArgument:&orient atIndex:3];
                [inv invoke];
                done = YES;
            }
        }

        // Run runloop briefly to process callbacks
        NSDate* deadline = [NSDate dateWithTimeIntervalSinceNow:2.0];
        while (!done && [[NSDate date] compare:deadline] == NSOrderedAscending) {
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                    beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
        }
        if (tapErr) {
            fprintf(stderr, "tap error: %s\n", [[tapErr localizedDescription] UTF8String]);
            return 1;
        }
        printf("ok\n");
    }
    else if ([cmd isEqualToString:@"swipe"]) {
        if (argc < 5) { fprintf(stderr, "swipe needs x1 y1 x2 y2\n"); return 1; }
        double x1 = atof(argv[2]), y1 = atof(argv[3]);
        double x2 = atof(argv[4]), y2 = atof(argv[5]);
        double duration = argc > 6 ? atof(argv[6]) : 0.3;
        CGPoint from = CGPointMake(x1, y1);
        CGPoint to   = CGPointMake(x2, y2);

        __block BOOL done = NO;
        SEL sel = NSSelectorFromString(@"pressAtPoint:forDuration:liftAtPoint:velocity:orientation:name:handler:");
        if ([gen respondsToSelector:sel]) {
            // complex signature â€” use simple drag instead
        }
        // Try swipe via dragFromPoint:toPoint:
        SEL dragSel = NSSelectorFromString(@"dragFromPoint:toPoint:duration:orientation:handler:");
        if ([gen respondsToSelector:dragSel]) {
            NSMethodSignature* sig = [gen methodSignatureForSelector:dragSel];
            NSInvocation* inv = [NSInvocation invocationWithMethodSignature:sig];
            [inv setSelector:dragSel];
            [inv setTarget:gen];
            [inv setArgument:&from atIndex:2];
            [inv setArgument:&to   atIndex:3];
            [inv setArgument:&duration atIndex:4];
            int orient = 1;
            [inv setArgument:&orient atIndex:5];
            void (^handler)(NSError*) = ^(NSError* err) { done = YES; };
            [inv setArgument:&handler atIndex:6];
            [inv invoke];
        }
        NSDate* deadline = [NSDate dateWithTimeIntervalSinceNow:duration + 1.0];
        while (!done && [[NSDate date] compare:deadline] == NSOrderedAscending) {
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                                    beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
        }
        printf("ok\n");
    }
    return 0;
}
"""

# Simpler IOHIDEvent approach that runs inside /var/jb/usr/bin/ (where code runs fine)
# Uses the platform-application entitlement which Dopamine allows from /var/jb
TAP_HID_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <mach/mach_time.h>
#include <CoreFoundation/CoreFoundation.h>

typedef void* IOHIDEventSystemClientRef;
typedef struct __IOHIDEvent* IOHIDEventRef;

extern IOHIDEventSystemClientRef IOHIDEventSystemClientCreate(CFAllocatorRef alloc, int type, int flags, void* p, int n);
extern void IOHIDEventSystemClientDispatchEvent(IOHIDEventSystemClientRef c, IOHIDEventRef e);
extern IOHIDEventRef IOHIDEventCreateDigitizerFingerEvent(
    CFAllocatorRef alloc, uint64_t timestamp,
    uint32_t index, uint32_t identity, uint32_t eventMask,
    double x, double y, double z,
    double tipPressure, double twist,
    uint32_t options, uint32_t buttonMask, uint32_t fingerMask);

static void send_finger(IOHIDEventSystemClientRef client, double x, double y,
                        int touching, int quality) {
    uint64_t t = mach_absolute_time();
    // eventMask: touch=1, range=2 when down; both 0 when up
    uint32_t mask = touching ? 3 : 0;
    IOHIDEventRef e = IOHIDEventCreateDigitizerFingerEvent(
        kCFAllocatorDefault, t, 0, 1, mask, x, y, 0,
        touching ? 1.0 : 0.0, 0, 0, touching ? 1 : 0, 0);
    if (e) {
        IOHIDEventSystemClientDispatchEvent(client, e);
        CFRelease(e);
    }
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        fprintf(stderr, "usage: tap_hid tap <x> <y>\n       tap_hid swipe <x1> <y1> <x2> <y2>\n");
        return 1;
    }
    IOHIDEventSystemClientRef client = IOHIDEventSystemClientCreate(kCFAllocatorDefault, 0, 0, NULL, 0);
    if (!client) { fprintf(stderr, "failed to create HID client\n"); return 1; }

    if (strcmp(argv[1], "tap") == 0) {
        double x = atof(argv[2]), y = atof(argv[3]);
        send_finger(client, x, y, 1, 1);
        usleep(80000);
        send_finger(client, x, y, 0, 0);
        printf("ok\n");
    } else if (strcmp(argv[1], "swipe") == 0 && argc >= 6) {
        double x1=atof(argv[2]), y1=atof(argv[3]);
        double x2=atof(argv[4]), y2=atof(argv[5]);
        int steps = argc > 6 ? atoi(argv[6]) : 20;
        send_finger(client, x1, y1, 1, 1);
        for (int i = 1; i <= steps; i++) {
            usleep(16000);
            send_finger(client, x1+(x2-x1)*i/steps, y1+(y2-y1)*i/steps, 1, 1);
        }
        usleep(50000);
        send_finger(client, x2, y2, 0, 0);
        printf("ok\n");
    }
    CFRelease(client);
    return 0;
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
    with sftp.open('/tmp/tap_hid.c', 'w') as f:    f.write(TAP_HID_C)
    with sftp.open('/tmp/tap_xctest.m', 'w') as f:  f.write(TAP_XCTEST_M)
    with sftp.open('/tmp/tap_hid.ent', 'w') as f:   f.write(TAP_ENTITLEMENTS)
    sftp.close()

    # â”€â”€ Approach 1: IOHIDEvent binary in /var/jb/usr/bin/ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print('=== Approach 1: IOHIDEvent binary ===')
    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -o /var/jb/usr/bin/tap_hid /tmp/tap_hid.c '
        '-framework CoreFoundation -framework IOKit 2>&1"; echo compile:$?',
        'compile tap_hid', timeout=60)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"ldid -S/tmp/tap_hid.ent /var/jb/usr/bin/tap_hid && echo signed"',
        'sign tap_hid')

    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/tap_hid tap 187 333; echo exit:$?',
        'test tap_hid (center of screen)')

    # â”€â”€ Approach 2: XCEventGenerator binary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print('=== Approach 2: XCEventGenerator ===')
    run('ls /Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/ 2>/dev/null | head -5',
        'XCTAutomationSupport exists')
    run('ls /Developer/usr/lib/ 2>/dev/null | head -10', 'Developer usr lib')

    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"clang -fobjc-arc -framework Foundation -framework CoreGraphics '
        '-o /var/jb/usr/bin/tap_xctest /tmp/tap_xctest.m 2>&1"; echo compile:$?',
        'compile tap_xctest', timeout=60)

    run('echo one | /var/jb/usr/bin/sudo -S -p "" sh -c '
        '"ldid -S/tmp/tap_hid.ent /var/jb/usr/bin/tap_xctest && echo signed"',
        'sign tap_xctest')

    run('echo one | /var/jb/usr/bin/sudo -S -p "" '
        '/var/jb/usr/bin/tap_xctest tap 187 333; echo exit:$?',
        'test tap_xctest (center of screen)')

    # â”€â”€ Check opainject dylib injection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    print('=== Approach 3: opainject into SpringBoard ===')
    sb_pid = run('ps aux | grep SpringBoard | grep -v grep | awk \'{print $2}\' | head -1',
                 'springboard pid').strip()
    print(f'SpringBoard PID: {sb_pid}')

    if sb_pid:
        run(f'echo one | /var/jb/usr/bin/sudo -S -p "" '
            f'/var/jb/basebin/opainject {sb_pid} /tmp/tap_hook.dylib 2>&1',
            'opainject tap_hook.dylib')
        time.sleep(2)
        run('ls -la /tmp/tap_sock 2>/dev/null || echo "no socket"', 'socket after inject')

    c.close()
finally:
    fwd.terminate()
