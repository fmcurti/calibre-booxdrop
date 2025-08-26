import re
from types import SimpleNamespace

from calibre.utils.config import JSONConfig
from calibre.devices.interface import DevicePlugin, BookList

from .booxdrop import BooxDropAPI
from .config import build_config_widget, normalize_url


plugin_prefs = JSONConfig('plugins/BooxDropDevice')
plugin_prefs.defaults['base_url'] = 'http://192.168.0.20:8085'

def _gb_to_bytes(text):
    # Accept "32GB", "14.6GB", etc.
    m = re.search(r'([\d.]+)\s*GB', text or '', re.I)
    return int(float(m.group(1)) * (1024**3)) if m else 0

class BooxDropDevice(DevicePlugin):
    name = 'BooxDrop Device'
    description = 'BooxDrop integration for Calibre'
    author = 'fmcurti'
    version = (0, 0, 1)
    minimum_calibre_version = (6, 0, 0)
    supported_platforms = ['windows', 'osx', 'linux']

    # Formats Calibre can send (it will auto-convert if needed)
    FORMATS = ['epub', 'azw3', 'mobi', 'pdf']

    # We manage presence (HTTP ping) instead of USB detection
    MANAGES_DEVICE_PRESENCE = True

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.base_url = normalize_url(plugin_prefs['base_url'])
        self.boox_api = BooxDropAPI(self.base_url)
        self._connected = False
        self._model = 'Unknown Model'
        self._total_bytes = 0
        self._free_bytes = -1
        self.progress_reporter = None
        
    @classmethod
    def settings(cls):
        return SimpleNamespace(format_map=list(cls.FORMATS))
    
    def set_progress_reporter(self, progress_reporter):
        self.progress_reporter = progress_reporter

    # Auto-detect presence (no Start/Stop button required)
    def detect_managed_devices(self, devices_on_system, force_refresh=False):
        try:
            info = self.boox_api.device_info()
            return info
        except Exception:
            return None

    def open(self, connected_device, library_uuid):
        # connected_device is whatever detect_managed_devices() returned
        self._model = connected_device.get('model', 'Unknown Model')

        total_gb = connected_device.get('storageTotal', '0GB')
        used_gb = connected_device.get('storageUsed', '0GB')

        total = _gb_to_bytes(total_gb)
        used = _gb_to_bytes(used_gb)

        self._total_bytes = total
        self._free_bytes = max(total - used, 0)

        self._connected = True

    def eject(self):
        self._connected = False

    # --- Required space APIs: must accept end_session and return BYTES ---
    def total_space(self, end_session=True):
        # [main, cardA, cardB]
        return [self._total_bytes, 0, 0]

    def free_space(self, end_session=True):
        # [main, cardA, cardB]
        return [self._free_bytes, -1, -1]

    # For non-card devices
    def card_prefix(self, end_session=True):
        return (None, None)

    def books(self, oncard=None, end_session=True):
        # Return an empty BookList for now (you can populate later)
        return BookList(oncard, prefix='/', settings=None)

    def get_device_information(self, end_session=True):
        # (device name, device version, software version, MIME type)
        return (self._model, '1.0', '1.0', 'application/x-booxdrop')

    # Calibre calls this to actually transfer the files
    def upload_books(self, files, names, on_card=None, end_session=True, metadata=None):
        locations = []
        for src_path, dest_name in zip(files, names):
            if self.progress_reporter:
                self.progress_reporter(-1)  # unknown progress
            ok = self.boox_api.upload_book(src_path, dest_name)
            if ok:
                locations.append((on_card, '/' + dest_name, None))
        return locations

    # Keep metadata sync no-op to avoid NotImplementedError callbacks
    @classmethod
    def add_books_to_metadata(cls, locations, metadata, booklists):
        return

    @classmethod
    def remove_books_from_metadata(cls, paths, booklists):
        return
    
    def sync_booklists(self, booklists, end_session=True):
        # No-op for now
        return

    def delete_books(self, paths, end_session=True):
        # TODO: Implement book deletion
        return
    
    # --- Preferences UI ---------------------------------------------------
    def is_customizable(self):
        return True
    
    def config_widget(self):
        return build_config_widget(self.base_url)

    def save_settings(self, config_widget):
        new_url = normalize_url(config_widget.url_edit.text())
        plugin_prefs['base_url'] = new_url

        # Apply immediately in this session
        self.base_url = new_url
        self.boox_api = BooxDropAPI(self.base_url)