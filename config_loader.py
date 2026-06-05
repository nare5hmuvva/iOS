"""Shared config loader for all project scripts.

Reads ios-pentest-lab/relay/config.env, with environment variable overrides.
Usage:
    from config_loader import cfg
    ip   = cfg['IPHONE_IP']
    port = cfg['SSH_PORT']
"""
import os
from pathlib import Path

_HERE = Path(__file__).parent
_ENV_FILE = _HERE / 'ios-pentest-lab' / 'relay' / 'config.env'

def _load() -> dict:
    defaults = {
        'IPHONE_IP':        '',
        'RELAY_IP':         '',
        'INTERCEPT_HOST':   '',
        'INTERCEPT_PORT':   '8082',
        'SSH_FORWARD_PORT': '2222',
        'FRIDA_PORT':       '27042',
        'DASHBOARD_PORT':   '8081',
        'USB_FLUX_PORT':    '5000',
        'VNC_PORT':         '5900',
        'NOVNC_PORT':       '6080',
    }
    result = dict(defaults)
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                result[k.strip()] = v.split('#')[0].strip()
    # Environment variables take highest priority
    for k in list(result.keys()):
        if k in os.environ:
            result[k] = os.environ[k]
    # Convenience aliases
    result['SSH_PORT']   = result.get('SSH_FORWARD_PORT', '2222')
    result['FRIDA_PORT'] = result.get('FRIDA_PORT', '27042')
    return result

cfg = _load()

def get(key: str, default: str = '') -> str:
    return cfg.get(key, default)

def get_int(key: str, default: int = 0) -> int:
    try:
        return int(cfg.get(key, str(default)))
    except (ValueError, TypeError):
        return default
