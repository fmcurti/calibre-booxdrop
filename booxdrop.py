import urllib.request
import urllib.parse
import json

class BooxDropAPI:
    def __init__(self, base_url):
        self.base_url = base_url

    def device_info(self):
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/device") as response:
                if response.getcode() == 200:
                    return json.loads(response.read())
        except Exception as e:
            print("Error occurred:", e)
        return None

    def get_folders(self) -> list[str]:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/library/tree") as response:
                if response.getcode() == 200:
                    data = json.loads(response.read())
                    children = data.get("children", [])
                    folders = map(lambda x: x['library']['name'], children)
                    return list(folders)
        except:
            pass
        return []

    def upload_book(self, book_path: str, dest_name: str) -> bool:
        try:
            with open(book_path, 'rb') as f:
                # Create multipart form data for file upload
                boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
                body = f'------WebKitFormBoundary7MA4YWxkTrZu0gW\r\nContent-Disposition: form-data; name="file"; filename="{dest_name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                body += f.read()
                body += b'\r\n------WebKitFormBoundary7MA4YWxkTrZu0gW--\r\n'
                
                req = urllib.request.Request(
                    f"{self.base_url}/api/storage/upload",
                    data=body,
                    headers={
                        'User-Agent': 'Calibre',
                        'Content-Type': f'multipart/form-data; boundary={boundary}',
                        'Content-Length': str(len(body))
                    }
                )
                
                with urllib.request.urlopen(req) as response:
                    return response.getcode() == 200
        except:
            pass
        return False