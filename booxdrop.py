import http.client
import json
import os
import shutil
import urllib.parse
import urllib.request

from calibre.prints import debug_print

PROBE_TIMEOUT = 2.0
LIST_TIMEOUT = 10.0
UPLOAD_TIMEOUT = 600.0
DOWNLOAD_TIMEOUT = 600.0
UPLOAD_CHUNK = 64 * 1024
LIST_PAGE_SIZE = 100
MULTIPART_BOUNDARY = '----CalibreBooxDropBoundary7MA4YWxkTrZu0gW'


def _encode_args(value) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, separators=(',', ':'))
    return urllib.parse.quote(value, safe='')


class BooxDropAPI:
    def __init__(self, base_url):
        self.base_url = base_url

    def device_info(self):
        url = f"{self.base_url}/api/device"
        try:
            with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as response:
                if response.getcode() == 200:
                    return json.loads(response.read())
        except Exception as e:
            debug_print('BOOXDROP: device_info failed for', url, '->', e)
        return None

    def get_folders(self) -> list[str]:
        url = f"{self.base_url}/api/library/tree"
        try:
            with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as response:
                if response.getcode() == 200:
                    data = json.loads(response.read())
                    children = data.get("children", [])
                    return [c['library']['name'] for c in children]
        except Exception as e:
            debug_print('BOOXDROP: get_folders failed for', url, '->', e)
        return []

    def _library_ids(self) -> list:
        """Return [None, uid1, uid2, ...] — the root plus every library UUID
        we can reach by walking /api/library/tree."""
        url = f"{self.base_url}/api/library/tree"
        ids = [None]
        try:
            with urllib.request.urlopen(url, timeout=LIST_TIMEOUT) as response:
                if response.getcode() != 200:
                    return ids
                tree = json.loads(response.read())
        except Exception as e:
            debug_print('BOOXDROP: library tree failed:', e)
            return ids

        def walk(node):
            for child in node.get('children', []) or []:
                lib = child.get('library', {}) or {}
                uid = lib.get('idString')
                if uid:
                    ids.append(uid)
                walk(child)

        walk(tree)
        return ids

    def _list_library(self, library_uid):
        """Paginated /api/library for one library uuid (or None for root)."""
        offset = 0
        books = []
        while True:
            args = {
                'limit': LIST_PAGE_SIZE,
                'offset': offset,
                'sortBy': 'CreationTime',
                'order': 'Desc',
                'libraryUniqueId': library_uid,
            }
            url = f"{self.base_url}/api/library?args={_encode_args(args)}"
            try:
                with urllib.request.urlopen(url, timeout=LIST_TIMEOUT) as response:
                    if response.getcode() != 200:
                        break
                    payload = json.loads(response.read())
            except Exception as e:
                debug_print('BOOXDROP: list_library failed', library_uid, '->', e)
                break

            batch = payload.get('visibleBookList', []) or []
            if not batch:
                break
            books.extend(batch)
            if len(batch) < LIST_PAGE_SIZE:
                break
            offset += LIST_PAGE_SIZE
        return books

    def list_books(self):
        """All books across all libraries, returned as metadata dicts.

        We merge the outer entry's coverPath into the metadata dict because
        the BooxDrop API exposes coverPath at the entry level (sibling of
        metadata), not inside it."""
        results = []
        for uid in self._library_ids():
            for entry in self._list_library(uid):
                md = entry.get('metadata') or {}
                if not md:
                    continue
                cover_path = entry.get('coverPath')
                if cover_path and 'coverPath' not in md:
                    md['coverPath'] = cover_path
                results.append(md)
        return results

    def delete_book(self, path: str) -> bool:
        url = f"{self.base_url}/api/storage/delete?args={_encode_args(path)}"
        req = urllib.request.Request(url, method='DELETE')
        try:
            with urllib.request.urlopen(req, timeout=LIST_TIMEOUT) as response:
                if response.getcode() != 200:
                    return False
                payload = json.loads(response.read() or b'{}')
                return bool(payload.get('successful', True))
        except Exception as e:
            debug_print('BOOXDROP: delete_book failed for', path, '->', e)
            return False

    def download_book(self, path: str, outfile) -> bool:
        url = (f"{self.base_url}/api/storage/file?args={_encode_args(path)}"
               '&sender=web')
        try:
            with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response:
                if response.getcode() != 200:
                    return False
                shutil.copyfileobj(response, outfile, length=UPLOAD_CHUNK)
                return True
        except Exception as e:
            debug_print('BOOXDROP: download_book failed for', path, '->', e)
            return False

    def fetch_cover(self, path: str):
        url = (f"{self.base_url}/api/storage/file?args={_encode_args(path)}"
               '&sender=web')
        try:
            with urllib.request.urlopen(url, timeout=LIST_TIMEOUT) as response:
                if response.getcode() != 200:
                    return None
                return response.read()
        except Exception as e:
            debug_print('BOOXDROP: fetch_cover failed for', path, '->', e)
            return None

    def upload_book(self, book_path: str, dest_name: str, dir: str = None, progress=None):
        """Upload a file via POST /api/storage/upload.

        If `dir` is set, BooxDrop writes the file under that directory (useful
        for targeting an SD card or a non-default folder). Otherwise BooxDrop
        defaults to /storage/emulated/0/Books/.

        Returns the device-side absolute path where the file was saved
        (from the response's `message` field, so collision-renames like
        `Book_1.epub` are captured correctly), or None on failure.
        """
        try:
            file_size = os.path.getsize(book_path)

            field_parts = []
            if dir:
                field_parts.append(
                    f'--{MULTIPART_BOUNDARY}\r\n'
                    f'Content-Disposition: form-data; name="dir"\r\n\r\n'
                    f'{dir}\r\n'.encode()
                )
            field_parts.append((
                f'--{MULTIPART_BOUNDARY}\r\n'
                f'Content-Disposition: form-data; name="file"; filename="{dest_name}"\r\n'
                f'Content-Type: application/octet-stream\r\n\r\n'
            ).encode())
            prefix = b''.join(field_parts)
            suffix = f'\r\n--{MULTIPART_BOUNDARY}--\r\n'.encode()
            total = len(prefix) + file_size + len(suffix)

            parts = urllib.parse.urlsplit(self.base_url)
            host = parts.hostname
            port = parts.port or (443 if parts.scheme == 'https' else 80)
            path = parts.path.rstrip('/') + '/api/storage/upload'
            conn_cls = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
            conn = conn_cls(host, port, timeout=UPLOAD_TIMEOUT)
            try:
                conn.putrequest('POST', path)
                conn.putheader('User-Agent', 'Calibre')
                conn.putheader('Content-Type', f'multipart/form-data; boundary={MULTIPART_BOUNDARY}')
                conn.putheader('Content-Length', str(total))
                conn.endheaders()

                sent = 0
                conn.send(prefix)
                sent += len(prefix)
                if progress:
                    progress(sent, total)

                with open(book_path, 'rb') as f:
                    while True:
                        chunk = f.read(UPLOAD_CHUNK)
                        if not chunk:
                            break
                        conn.send(chunk)
                        sent += len(chunk)
                        if progress:
                            progress(sent, total)

                conn.send(suffix)
                sent += len(suffix)
                if progress:
                    progress(sent, total)

                resp = conn.getresponse()
                body = resp.read()
                if resp.status != 200:
                    return None
                try:
                    payload = json.loads(body or b'{}')
                except ValueError:
                    payload = {}
                if not payload.get('successful', True):
                    return None
                return payload.get('message')
            finally:
                conn.close()
        except Exception as e:
            debug_print('BOOXDROP: upload_book failed for', dest_name, '->', e)
        return None
