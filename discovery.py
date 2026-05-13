import json
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from calibre.prints import debug_print

DEFAULT_PORT = 8085
PROBE_TIMEOUT = 0.5
SCAN_WORKERS = 64


def _local_ipv4s():
    """Best-effort: open a UDP socket to a public address and read the
    bound local IP. Returns a list with that single IP (or empty)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return [s.getsockname()[0]]
        finally:
            s.close()
    except OSError:
        return []


def _slash24_hosts(ip):
    prefix = '.'.join(ip.split('.')[:3])
    return [f'{prefix}.{i}' for i in range(1, 255)]


def _probe(host, port=DEFAULT_PORT):
    url = f'http://{host}:{port}/api/device'
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as r:
            if r.getcode() != 200:
                return None
            info = json.loads(r.read())
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    if info.get('type') != 'server' or not info.get('model'):
        return None
    return (f'http://{host}:{port}', info)


def discover(port=DEFAULT_PORT, max_workers=SCAN_WORKERS):
    """Scan the local /24 for BooxDrop devices. Returns list of (url, info)."""
    hits = []
    for ip in _local_ipv4s():
        debug_print('BOOXDROP: scanning subnet from', ip)
        hosts = _slash24_hosts(ip)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for r in ex.map(lambda h: _probe(h, port), hosts):
                if r:
                    hits.append(r)
    debug_print('BOOXDROP: discover found', len(hits), 'devices')
    return hits


def discover_first(port=DEFAULT_PORT):
    hits = discover(port=port)
    return hits[0] if hits else (None, None)
