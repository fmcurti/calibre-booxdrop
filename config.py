import re

from .booxdrop import BooxDropAPI
from qt.core import QWidget, QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QMessageBox

def normalize_url(url: str) -> str:
    url = url.strip()
    if not re.match(r'^https?://', url, re.I):
        url = 'http://' + url
    # strip trailing slashes
    return url.rstrip('/')

def build_config_widget(current_base_url: str) -> QWidget:
    w = QWidget()
    lay = QFormLayout(w)

    url_edit = QLineEdit(current_base_url, w)
    url_edit.setPlaceholderText('http://host:port')
    w.url_edit = url_edit  # attach so save_settings can read it

    row = QWidget(w)
    row_lay = QHBoxLayout(row)
    row_lay.setContentsMargins(0, 0, 0, 0)  
    row_lay.addWidget(url_edit)
    test_btn = QPushButton('Test', row)

    def _test():
        trial = normalize_url(url_edit.text())
        try:
            # ping the device
            api = BooxDropAPI(trial)
            info = api.device_info()
            if info:
                QMessageBox.information(w, 'BooxDrop', f"Connected: {info.get('model','Unknown')}")
            else:
                QMessageBox.warning(w, 'BooxDrop', 'No response from device.')
        except Exception as e:
            QMessageBox.critical(w, 'BooxDrop', f'Error: {e}')

    test_btn.clicked.connect(_test)
    row_lay.addWidget(test_btn)

    lay.addRow('BooxDrop URL', row)
    return w