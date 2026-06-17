import os
import urllib.request

libs = {
    "public/lib/marked.min.js": "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
    "public/lib/highlight.min.js": "https://cdn.jsdelivr.net/npm/highlight.js@11.7.0/highlight.min.js",
    "public/lib/atom-one-dark.css": "https://cdn.jsdelivr.net/npm/highlight.js@11.7.0/styles/atom-one-dark.css"
}

os.makedirs("public/lib", exist_ok=True)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

for path, url in libs.items():
    print(f"Downloading {url} to {path}...")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            with open(path, "wb") as f:
                f.write(response.read())
        print("Success.")
    except Exception as e:
        print(f"Error downloading {url}: {e}")
