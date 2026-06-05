import asyncio
import socket

async def check_frida():
    from pymobiledevice3.lockdown import create_using_usbmux
    lockdown = await create_using_usbmux()
    print('Device:', lockdown.product_version, lockdown.identifier[:16])

    # Check for running frida-server process via DVT
    try:
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.process_control import ProcessControl
        async with DvtProvider(lockdown) as dvt:
            async with ProcessControl(dvt) as pc:
                try:
                    pid = await pc.process_identifier_for_bundle_identifier('re.frida.server')
                    print('frida-server PID (by bundle):', pid)
                except Exception as e:
                    print('bundle lookup:', e)
    except Exception as e:
        print('DVT ProcessControl:', e)

    # Try to connect to frida port 27042 via usbmux TCP tunnel
    try:
        from pymobiledevice3.usbmux import UsbmuxClient
        print('UsbmuxClient available')
    except ImportError:
        pass

    try:
        from pymobiledevice3.tunneld import TunneldClient
        print('TunneldClient available')
    except ImportError:
        pass

    # Check AFC for frida-related files in accessible locations
    try:
        from pymobiledevice3.services.afc import AfcService
        async with AfcService(lockdown) as afc:
            try:
                items = await afc.listdir('/var/mobile/Media')
                print('AFC /var/mobile/Media accessible, items:', len(items))
            except Exception as e:
                print('AFC listdir:', e)
    except Exception as e:
        print('AFC service:', e)

    # Check via diagnostics
    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        async with DiagnosticsService(lockdown) as diag:
            info = await diag.info()
            print('Diagnostics available')
    except Exception as e:
        print('Diagnostics:', e)

asyncio.run(check_frida())
