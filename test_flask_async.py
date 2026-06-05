import asyncio
import traceback

async def get_info():
    from pymobiledevice3.lockdown import create_using_usbmux
    lockdown = await create_using_usbmux()
    name = await lockdown.get_value(domain=None, key='DeviceName')
    return {'name': str(name), 'ios': lockdown.product_version, 'udid': lockdown.identifier}

# Simulate what run_async does in Flask
print("[*] Test 1: asyncio.run()")
try:
    result = asyncio.run(get_info())
    print("[OK]", result)
except Exception as e:
    traceback.print_exc()

print("\n[*] Test 2: new_event_loop()")
try:
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(get_info())
    loop.close()
    print("[OK]", result)
except Exception as e:
    traceback.print_exc()

print("\n[*] Test 3: SelectorEventLoop")
try:
    loop = asyncio.SelectorEventLoop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(get_info())
    loop.close()
    print("[OK]", result)
except Exception as e:
    traceback.print_exc()
