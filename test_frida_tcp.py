"""
Connect to frida-server via TCP (USB tunnel on port 27042) instead of USB mode.
This bypasses the frida USB transport that crashes on Dopamine.
"""
import frida, subprocess, sys, time, threading

# Forward device port 27042 -> localhost:27042
fwd = subprocess.Popen(
    [sys.executable, '-m', 'pymobiledevice3', 'usbmux', 'forward', '27042', '27042'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
time.sleep(2)

try:
    print('Connecting to frida-server via TCP tunnel (localhost:27042)...')
    mgr = frida.get_device_manager()
    device = mgr.add_remote_device('127.0.0.1:27042')
    print('Device:', device)

    procs = device.enumerate_processes()
    print(f'Processes: {len(procs)}')

    # Find SpringBoard
    sb = next((p for p in procs if p.name == 'SpringBoard'), None)
    if sb:
        print(f'SpringBoard PID: {sb.pid}')
        session = device.attach(sb.pid)
        print('Attached to SpringBoard!')

        script = session.create_script("""
'use strict';
var b = ObjC.classes.UIScreen.mainScreen().bounds();
var sw = b.size.width, sh = b.size.height;
console.log('Screen: ' + sw + 'x' + sh);

// Load XCTAutomationSupport
var xctLoaded = false;
try {
    Module.load('/Developer/Library/PrivateFrameworks/XCTAutomationSupport.framework/XCTAutomationSupport');
    xctLoaded = ObjC.classes.XCEventGenerator != null;
} catch(e) {}
console.log('XCT loaded: ' + xctLoaded);

rpc.exports = {
    info: function() { return {w:sw, h:sh, xct:xctLoaded}; },
    tap: function(x, y) {
        x=+x; y=+y;
        if (!xctLoaded) return 'xct_not_loaded';
        try {
            var gen = ObjC.classes.XCEventGenerator.sharedGenerator();
            gen.tapAtPoint_orientation_handler_(
                {x:x, y:y}, 1,
                new ObjC.Block({retType:'void', argTypes:['pointer'], implementation:function(){}})
            );
            return 'ok:tapAtPoint';
        } catch(e1) {
            try {
                ObjC.classes.XCEventGenerator.sharedGenerator()
                    .pressAtPoint_forDuration_liftAtPoint_velocity_orientation_name_handler_(
                        {x:x,y:y}, 0.0, {x:x,y:y}, 1.5, 1, 'tap',
                        new ObjC.Block({retType:'void',argTypes:['pointer'],implementation:function(){}})
                    );
                return 'ok:pressAtPoint';
            } catch(e2) { return 'err:'+e2; }
        }
    }
};
""")
        msgs = []
        script.on('message', lambda m, d: msgs.append(m) or print('[msg]', m))
        script.load()
        time.sleep(1)

        info = script.exports.invoke('info', [])
        print('Info:', info)

        if info.get('xct'):
            cx, cy = info['w']//2, info['h']//2
            print(f'Tapping center ({cx}, {cy})...')
            result = script.exports.invoke('tap', [cx, cy])
            print('Result:', result)

        session.detach()
    else:
        print('SpringBoard not found in process list')

finally:
    fwd.terminate()
    print('Done.')
