import hashlib
import os
import re
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

from calibre.constants import numeric_version as calibre_version
from calibre.devices.errors import FreeSpaceError, OpenFeedback
from calibre.devices.interface import DevicePlugin
from calibre.devices.usbms.books import Book, CollectionsBookList
from calibre.prints import debug_print
from calibre.utils.config import JSONConfig

from calibre_plugins.booxdrop.booxdrop import BooxDropAPI
from calibre_plugins.booxdrop.config import build_config_widget, normalize_url
from calibre_plugins.booxdrop.discovery import discover


plugin_prefs = JSONConfig('plugins/BooxDropDevice')
plugin_prefs.defaults['base_url'] = 'http://192.168.0.20:8085'
plugin_prefs.defaults['sd_card_dir'] = ''   # empty = no SD card configured

UID_KEYS = ('deviceUid', 'deviceId', 'uuid', 'serialNumber', 'serial', 'mac', 'id')


def _normalize_dir(path):
    """Strip trailing slashes; empty returns ''."""
    if not path:
        return ''
    return path.rstrip('/')


def _path_belongs_to(path, folder):
    """True iff `path` is under `folder` (folder is a directory)."""
    if not folder:
        return False
    return path == folder or path.startswith(folder + '/')


def _detect_sd_card_dir(paths):
    """Inspect device-side paths and return a best-guess SD-card upload
    directory, or '' if no external storage is in use.

    Android mounts internal storage at /storage/emulated/0 and SD cards
    at /storage/<volume-uuid>/. Any path under /storage/* that isn't
    /storage/emulated/ is therefore external.
    """
    sd_books = []
    sd_root = ''
    for p in paths or ():
        if not p.startswith('/storage/'):
            continue
        if p.startswith('/storage/emulated/'):
            continue
        parts = p.split('/')
        if len(parts) < 3:
            continue
        sd_root = f'/storage/{parts[2]}'
        sd_books.append(p)

    if not sd_root:
        return ''

    # Prefer the directory of an actual book on the SD; fall back to
    # /<mount>/Books (BOOX's convention) when the card is empty.
    if sd_books:
        return '/'.join(sd_books[0].split('/')[:-1])
    return sd_root + '/Books'

DISCOVERY_FAIL_THRESHOLD = 5      # consecutive failed probes before scanning (~10s)
DISCOVERY_COOLDOWN_SECONDS = 60   # don't rescan more often than this


def _gb_to_bytes(text):
    m = re.search(r'([\d.]+)\s*GB', text or '', re.I)
    return int(float(m.group(1)) * (1024**3)) if m else 0


def _extract_uid(info, base_url):
    for key in UID_KEYS:
        v = info.get(key) if info else None
        if v:
            return str(v)
    seed = (info.get('model', '') if info else '') + '|' + base_url
    return 'booxdrop-' + hashlib.sha1(seed.encode()).hexdigest()[:16]


def _parse_boox_date(text):
    if not text:
        return time.gmtime()
    s = str(text).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timetuple()
        except ValueError:
            continue
    return time.gmtime()


def _png_dims(data):
    if data and len(data) >= 24 and data[:8] == b'\x89PNG\r\n\x1a\n':
        try:
            return struct.unpack('>II', data[16:24])
        except struct.error:
            pass
    return (192, 256)


COVER_WORKERS = 8


class BooxDropDevice(DevicePlugin):
    name = 'BooxDrop Device'
    description = 'BooxDrop integration for Calibre'
    author = 'fmcurti'
    version = (0, 0, 13)
    minimum_calibre_version = (6, 0, 0)
    supported_platforms = ['windows', 'osx', 'linux']

    FORMATS = ['epub', 'azw3', 'mobi', 'pdf']

    MANAGES_DEVICE_PRESENCE = True

    booklist_class = CollectionsBookList
    book_class = Book

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._lock = threading.RLock()
        self.base_url = normalize_url(plugin_prefs['base_url'])
        self.sd_card_dir = _normalize_dir(plugin_prefs['sd_card_dir'])
        self.boox_api = BooxDropAPI(self.base_url)
        self._connected = False
        self._model = 'Unknown Model'
        self._total_bytes = 0
        self._free_bytes = -1
        self._device_uid = None
        self._library_uuid = ''
        self._connected_at = None
        self._last_probe_url = None
        self._last_probe_ok = None
        self._last_probe_error = None
        self._fail_count = 0
        self._last_discovery_at = 0.0
        self._cover_cache = {}
        self.progress_reporter = None

    @classmethod
    def settings(cls):
        return SimpleNamespace(format_map=list(cls.FORMATS))

    def set_progress_reporter(self, progress_reporter):
        self.progress_reporter = progress_reporter

    def _report(self, fraction, msg=''):
        if self.progress_reporter is not None:
            self.progress_reporter(fraction, msg)

    def _get_api(self):
        with self._lock:
            return self.boox_api, self.base_url

    def detect_managed_devices(self, devices_on_system, force_refresh=False):
        info, url, err = self._probe_once()
        with self._lock:
            self._last_probe_url = url
            self._last_probe_ok = bool(info)
            self._last_probe_error = err
            if info:
                self._fail_count = 0
                return info
            self._fail_count += 1
            should_discover = (
                self._fail_count >= DISCOVERY_FAIL_THRESHOLD
                and time.monotonic() - self._last_discovery_at >= DISCOVERY_COOLDOWN_SECONDS
            )

        if not should_discover:
            return None

        new_url = self._auto_discover()
        if not new_url:
            return None

        info, url, err = self._probe_once()
        with self._lock:
            self._last_probe_url = url
            self._last_probe_ok = bool(info)
            self._last_probe_error = err
            if info:
                self._fail_count = 0
        return info

    def _probe_once(self):
        api, url = self._get_api()
        try:
            info = api.device_info()
        except Exception as e:
            debug_print('BOOXDROP: probe error:', e)
            return None, url, str(e)
        return info, url, None if info else 'no response'

    def _auto_discover(self):
        with self._lock:
            self._last_discovery_at = time.monotonic()
            old_url = self.base_url
        debug_print('BOOXDROP: auto-discovery triggered (was', old_url + ')')

        try:
            hits = discover()
        except Exception as e:
            debug_print('BOOXDROP: auto-discovery error:', e)
            return None
        if not hits:
            debug_print('BOOXDROP: auto-discovery found nothing')
            return None

        new_url = hits[0][0]
        with self._lock:
            self.base_url = new_url
            self.boox_api = BooxDropAPI(new_url)
        plugin_prefs['base_url'] = new_url
        debug_print('BOOXDROP: auto-discovery switched URL', old_url, '->', new_url)
        return new_url

    def debug_managed_device_detection(self, devices_on_system, output):
        with self._lock:
            url = self._last_probe_url or self.base_url
            ok = self._last_probe_ok
            err = self._last_probe_error
            connected = self._connected
            model = self._model
        output.write(f'BooxDrop base URL: {url}\n')
        output.write(f'Last probe ok: {ok}\n')
        output.write(f'Last probe error: {err}\n')
        output.write(f'Connected: {connected}\n')
        output.write(f'Model: {model}\n')
        return bool(ok)

    def open(self, connected_device, library_uuid):
        debug_print('BOOXDROP: open', connected_device)
        if not isinstance(connected_device, dict) or not connected_device.get('model'):
            raise OpenFeedback('Could not read device info from BooxDrop. '
                               'Check that BooxDrop is enabled on the device.')

        total_gb = connected_device.get('storageTotal', '0GB')
        used_gb = connected_device.get('storageUsed', '0GB')
        total = _gb_to_bytes(total_gb)
        used = _gb_to_bytes(used_gb)

        with self._lock:
            self._model = connected_device.get('model', 'Unknown Model')
            self._total_bytes = total
            self._free_bytes = max(total - used, 0)
            self._device_uid = _extract_uid(connected_device, self.base_url)
            self._library_uuid = library_uuid or ''
            self._connected_at = datetime.now(timezone.utc)
            self._connected = True
            need_sd_detect = not self.sd_card_dir
            api = self.boox_api

        if need_sd_detect:
            try:
                paths = api.list_media_paths()
            except Exception as e:
                debug_print('BOOXDROP: SD auto-detect probe failed:', e)
                paths = []
            sd = _detect_sd_card_dir(paths)
            if sd:
                debug_print('BOOXDROP: auto-detected SD card at', sd)
                with self._lock:
                    self.sd_card_dir = sd
                plugin_prefs['sd_card_dir'] = sd

    def eject(self):
        debug_print('BOOXDROP: eject')
        with self._lock:
            self._connected = False

    def total_space(self, end_session=True):
        with self._lock:
            card_a = self._total_bytes if self.sd_card_dir else 0
            return [self._total_bytes, card_a, 0]

    def free_space(self, end_session=True):
        with self._lock:
            card_a = self._free_bytes if self.sd_card_dir else -1
            return [self._free_bytes, card_a, -1]

    def card_prefix(self, end_session=True):
        with self._lock:
            return (self.sd_card_dir or None, None)

    def books(self, oncard=None, end_session=True):
        bl = CollectionsBookList(oncard, prefix='/', settings=None)
        with self._lock:
            sd_dir = self.sd_card_dir
        if oncard == 'cardb':
            return bl
        if oncard == 'carda' and not sd_dir:
            return bl

        api, _ = self._get_api()
        try:
            entries = api.list_books()
        except Exception as e:
            debug_print('BOOXDROP: books() list failed:', e)
            return bl

        allowed = {'.' + f.lower() for f in self.FORMATS}
        seen = set()
        pending_covers = []
        for md in entries:
            path = md.get('location') or md.get('nativeAbsolutePath') or ''
            if not path or path in seen:
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext not in allowed:
                continue
            on_sd = _path_belongs_to(path, sd_dir)
            if oncard == 'carda' and not on_sd:
                continue
            if oncard is None and on_sd:
                continue
            seen.add(path)

            lpath = path.lstrip('/')
            book = Book('/', lpath, size=md.get('size'))
            book.title = md.get('title') or os.path.splitext(os.path.basename(path))[0]
            author_list = md.get('authorList') or []
            authors = md.get('authors') or ''
            if author_list:
                book.authors = list(author_list)
            elif authors:
                book.authors = [authors]
            tag_list = md.get('tagList') or []
            if tag_list:
                book.tags = list(tag_list)
            book.datetime = _parse_boox_date(md.get('updatedAt') or md.get('createdAt'))

            cover_path = md.get('coverPath')
            if cover_path:
                cached = self._cover_cache.get(cover_path)
                if cached:
                    self._attach_cover(book, cached)
                else:
                    pending_covers.append((book, cover_path))
            bl.add_book(book, replace_metadata=False)

        if pending_covers:
            self._fetch_covers(api, pending_covers)
        debug_print('BOOXDROP: books() returning', len(bl), 'entries')
        return bl

    def _fetch_covers(self, api, pending):
        unique = {}
        for book, path in pending:
            unique.setdefault(path, []).append(book)

        paths = list(unique.keys())
        with ThreadPoolExecutor(max_workers=COVER_WORKERS) as ex:
            data_list = list(ex.map(api.fetch_cover, paths))

        ok = 0
        for path, data in zip(paths, data_list):
            if not data:
                continue
            ok += 1
            self._cover_cache[path] = data
            for book in unique[path]:
                self._attach_cover(book, data)
        debug_print('BOOXDROP: fetched', ok, 'of', len(paths), 'covers')

    @staticmethod
    def _attach_cover(book, data):
        w, h = _png_dims(data)
        fmt = 'png' if data[:8] == b'\x89PNG\r\n\x1a\n' else 'jpg'
        book.cover_data = (fmt, data)
        book.thumbnail = (w, h, data)

    def get_device_information(self, end_session=True):
        with self._lock:
            model = self._model
            uid = self._device_uid or ''
            lib_uuid = self._library_uuid
            connected_at = self._connected_at

        connected_iso = connected_at.isoformat() if connected_at else ''
        driveinfo = {
            'main': {
                'device_store_uuid': uid,
                'device_name': model,
                'location_code': 'main',
                'prefix': '/',
                'last_library_uuid': lib_uuid,
                'calibre_version': '.'.join(str(x) for x in calibre_version),
                'date_last_connected': connected_iso,
            }
        }
        return (model, '1.0', '1.0', '', driveinfo)

    def upload_books(self, files, names, on_card=None, end_session=True, metadata=None):
        debug_print('BOOXDROP: upload_books count=', len(files), 'on_card=', on_card)
        with self._lock:
            api = self.boox_api
            sd_dir = self.sd_card_dir
        if on_card == 'carda':
            upload_dir = sd_dir or None
        elif on_card == 'cardb':
            raise OSError('BooxDrop only supports one SD card slot (card A).')
        else:
            upload_dir = None  # let BooxDrop pick its default for main memory

        try:
            total_size = sum(os.path.getsize(p) for p in files)
        except OSError as e:
            debug_print('BOOXDROP: could not stat input files:', e)
            total_size = 0

        with self._lock:
            free = self._free_bytes
        if free is not None and free >= 0 and total_size > free:
            raise FreeSpaceError(
                'Not enough memory on the device. Need %d bytes, have %d.'
                % (total_size, free)
            )

        locations = []
        n = len(files) or 1
        for i, (src_path, dest_name) in enumerate(zip(files, names)):
            base = i / n

            def progress(sent, total, base=base, n=n, dest_name=dest_name):
                self._report(base + (sent / total) / n, 'Transferring %s' % dest_name)

            saved_path = api.upload_book(src_path, dest_name, dir=upload_dir, progress=progress)
            if not saved_path:
                raise OSError('BooxDrop upload failed for %s' % dest_name)
            locations.append((saved_path, on_card))

        self._report(1.0, 'Transferring books to device...')
        return locations

    @classmethod
    def add_books_to_metadata(cls, locations, metadata, booklists):
        for location, mi in zip(locations, metadata):
            path = location[0]
            on_card = location[1] if len(location) > 1 else None
            blist = 2 if on_card == 'cardb' else 1 if on_card == 'carda' else 0
            if blist >= len(booklists) or booklists[blist] is None:
                continue
            lpath = path.lstrip('/')
            book = cls.book_class('/', lpath, other=mi)
            if book.size is None:
                book.size = getattr(mi, 'size', 0) or 0
            book.datetime = time.gmtime()
            added = booklists[blist].add_book(book, replace_metadata=True)
            if added is not None:
                added._new_book = True

    @classmethod
    def remove_books_from_metadata(cls, paths, booklists):
        for path in paths:
            for bl in booklists:
                if bl is None:
                    continue
                for book in list(bl):
                    if path.endswith(book.path) or book.path.endswith(path):
                        bl.remove_book(book)
                        break

    def sync_booklists(self, booklists, end_session=True):
        return

    def delete_books(self, paths, end_session=True):
        debug_print('BOOXDROP: delete_books', paths)
        api, _ = self._get_api()
        for path in paths:
            ok = api.delete_book(path)
            if not ok:
                raise OSError('BooxDrop delete failed for %s' % path)

    def get_file(self, path, outfile, end_session=True):
        debug_print('BOOXDROP: get_file', path)
        api, _ = self._get_api()
        ok = api.download_book(path, outfile)
        if not ok:
            raise OSError('BooxDrop download failed for %s' % path)

    def is_customizable(self):
        return True

    def config_widget(self):
        with self._lock:
            url = self.base_url
            sd_dir = self.sd_card_dir
        return build_config_widget(url, sd_dir)

    def save_settings(self, config_widget):
        new_url = normalize_url(config_widget.url_edit.text())
        new_sd = _normalize_dir(config_widget.sd_card_dir_edit.text().strip())
        plugin_prefs['base_url'] = new_url
        plugin_prefs['sd_card_dir'] = new_sd

        with self._lock:
            self.base_url = new_url
            self.sd_card_dir = new_sd
            self.boox_api = BooxDropAPI(new_url)

    def customization_help(self, gui=False):
        text = ('Set the BooxDrop URL displayed on your BOOX device '
                '(format: http://host:port). Both Calibre and the BOOX '
                'device must be on the same local network.')
        if gui:
            return '<p>' + text + '</p>'
        return text
