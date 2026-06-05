import asyncio
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.application_listing import ApplicationListing
from pymobiledevice3.services.os_trace import OsTraceService

async def test():
    lockdown = await create_using_usbmux()

    async with DvtProvider(lockdown) as dvt:
        print("[*] App listing via DVT...")
        try:
            async with ApplicationListing(dvt) as svc:
                apps = await svc.applist()
                print(f"[OK] {len(apps)} apps")
                for a in list(apps)[:6]:
                    name = str(a.get('CFBundleDisplayName', '?'))
                    bid  = a.get('CFBundleIdentifier', '?')
                    print(f"     {name:30s}  {bid}")
        except Exception as e:
            print("[FAIL] apps:", type(e).__name__, e)

    print("\n[*] Syslog (5 entries)...")
    try:
        async with OsTraceService(lockdown) as svc:
            i = 0
            async for entry in svc.syslog():
                ts  = str(entry.timestamp)
                pid = entry.pid
                msg = str(entry.message)[:80]
                print(f"     {ts}  [{pid}]  {msg}")
                i += 1
                if i >= 5:
                    break
    except Exception as e:
        print("[FAIL] syslog:", type(e).__name__, e)

asyncio.run(test())
