"""Test frida attach — tries different targets to find what works."""
import frida, time

device = frida.get_usb_device()
print(f"Device: {device.name}")

# List processes to pick a good target
procs = device.enumerate_processes()
print(f"Total processes: {len(procs)}")

# Candidates to try (from least to most privileged)
candidates = []
for p in procs:
    for name in ['MobileMail', 'MobileNotes', 'MobilePhone', 'SpringBoard', 'backboardd']:
        if p.name == name:
            candidates.append((p.pid, p.name))

# Also try a user app if running
for p in sorted(procs, key=lambda x: x.pid, reverse=True)[:5]:
    candidates.append((p.pid, p.name))

print("Candidates:", candidates[:8])

PROBE = """
'use strict';
var screenW = 0, screenH = 0;
try {
    var b = ObjC.classes.UIScreen.mainScreen().bounds();
    screenW = b.size.width; screenH = b.size.height;
} catch(e) {}

var xctLoaded = false;
var XCT_PATHS = [
    '/Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport',
    '/Developer/Library/PrivateFrameworks/XCTest.framework/XCTest',
];
for (var i = 0; i < XCT_PATHS.length; i++) {
    try { Module.load(XCT_PATHS[i]); } catch(e) {}
}
try { xctLoaded = ObjC.classes.XCEventGenerator != null; } catch(e) {}

rpc.exports = {
    info: function() { return {proc: Process.id, screen: screenW+'x'+screenH, xct: xctLoaded}; },
    tap: function(x, y) {
        x = +x; y = +y;
        if (xctLoaded) {
            try {
                var gen = ObjC.classes.XCEventGenerator.sharedGenerator();
                gen.tapAtPoint_orientation_handler_(
                    {x:x, y:y}, 1,
                    new ObjC.Block({retType:'void', argTypes:['pointer'], implementation: function(e){}})
                );
                return 'ok:tapAtPoint';
            } catch(e1) {
                try {
                    gen.pressAtPoint_forDuration_liftAtPoint_velocity_orientation_name_handler_(
                        {x:x,y:y}, 0.0, {x:x,y:y}, 1.5, 1, 'tap',
                        new ObjC.Block({retType:'void', argTypes:['pointer'], implementation: function(e){}})
                    );
                    return 'ok:pressAtPoint';
                } catch(e2) { return 'xct_err:'+e1+'|'+e2; }
            }
        }
        return 'xct_not_loaded';
    }
};
"""

session = None
for pid, name in candidates[:6]:
    print(f"\nTrying: {name} (PID {pid})")
    try:
        session = device.attach(pid)
        script = session.create_script(PROBE)
        msgs = []
        script.on('message', lambda m, d: msgs.append(m))
        script.load()
        info = script.exports.invoke('info', [])
        print(f"  [OK] Attached! info={info}")
        print(f"  Messages: {msgs}")

        if info.get('screen', '0x0') != '0x0':
            print(f"\n  Testing tap at center screen...")
            w, h = map(int, info['screen'].split('x'))
            res = script.exports.invoke('tap', [w//2, h//2])
            print(f"  tap({w//2},{h//2}) -> {res}")

        session.detach()
        break
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        try: session.detach()
        except: pass
