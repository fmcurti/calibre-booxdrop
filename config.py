import re

from qt.core import (
    Qt,
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from calibre_plugins.booxdrop.booxdrop import BooxDropAPI
from calibre_plugins.booxdrop.discovery import discover


def normalize_url(url: str) -> str:
    url = url.strip()
    if not re.match(r'^https?://', url, re.I):
        url = 'http://' + url
    return url.rstrip('/')


def build_config_widget(current_base_url: str, current_sd_card_dir: str = '') -> QWidget:
    w = QWidget()
    lay = QFormLayout(w)

    url_edit = QLineEdit(current_base_url, w)
    url_edit.setPlaceholderText('http://host:port')
    w.url_edit = url_edit

    sd_card_dir_edit = QLineEdit(current_sd_card_dir, w)
    sd_card_dir_edit.setPlaceholderText('/storage/XXXX-XXXX/Books/   (leave empty if no SD)')
    sd_card_dir_edit.setToolTip(
        "Path to a directory on your BOOX SD card. Leave empty if you don't "
        "have an SD card. When set, Calibre's 'Send to storage card A' menu "
        "writes there and the on-device pane partitions main memory vs card."
    )
    w.sd_card_dir_edit = sd_card_dir_edit

    def _validate():
        text = url_edit.text().strip()
        if not text:
            QMessageBox.warning(w, 'BooxDrop', 'Please enter a URL or click Discover.')
            return False
        return True

    w.validate = _validate

    row = QWidget(w)
    row_lay = QHBoxLayout(row)
    row_lay.setContentsMargins(0, 0, 0, 0)
    row_lay.addWidget(url_edit)

    discover_btn = QPushButton('Discover', row)
    test_btn = QPushButton('Test', row)

    def _test():
        trial = normalize_url(url_edit.text())
        try:
            api = BooxDropAPI(trial)
            info = api.device_info()
            if info:
                QMessageBox.information(
                    w, 'BooxDrop', f"Connected: {info.get('model', 'Unknown')}"
                )
            else:
                QMessageBox.warning(w, 'BooxDrop', 'No response from device.')
        except Exception as e:
            QMessageBox.critical(w, 'BooxDrop', f'Error: {e}')

    def _discover():
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        discover_btn.setEnabled(False)
        try:
            hits = discover()
        finally:
            discover_btn.setEnabled(True)
            QApplication.restoreOverrideCursor()

        if not hits:
            QMessageBox.warning(
                w, 'BooxDrop',
                'No BooxDrop devices found on the local network. '
                'Make sure BooxDrop is enabled on the BOOX and that both '
                'devices are on the same Wi-Fi.'
            )
            return

        url, info = hits[0]
        url_edit.setText(url)
        extra = ''
        if len(hits) > 1:
            extra = f'\n\n({len(hits)} devices found; using the first.)'
        QMessageBox.information(
            w, 'BooxDrop',
            f"Found {info.get('model', 'BOOX')} at {url}.{extra}"
        )

    discover_btn.clicked.connect(_discover)
    test_btn.clicked.connect(_test)
    row_lay.addWidget(discover_btn)
    row_lay.addWidget(test_btn)

    lay.addRow('BooxDrop URL', row)
    lay.addRow('SD card folder', sd_card_dir_edit)
    return w
