import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"
client = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)

for attempt in range(60):
    try:
        with client.open(f"{BASE}/api/health", timeout=2) as response:
            health = json.load(response)
        break
    except urllib.error.URLError:
        if attempt == 59:
            raise
        time.sleep(1)

if health["status"] not in {"configured", "configuration_required"}:
    raise RuntimeError(f"Unexpected health response: {health}")
with client.open(f"{BASE}/", timeout=5) as response:
    html = response.read().decode()
assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
if not assets or 'id="root"' not in html:
    raise RuntimeError("The built frontend was not served.")
for asset in assets:
    with client.open(f"{BASE}{asset}", timeout=5) as response:
        if not response.read():
            raise RuntimeError(f"Empty frontend asset: {asset}")
with client.open(f"{BASE}/api/prompts", timeout=5) as response:
    if not json.load(response):
        raise RuntimeError("The prompt catalog is empty.")
request = urllib.request.Request(
    f"{BASE}/api/session", method="POST", headers={"Origin": "http://localhost:8080"}
)
with client.open(request, timeout=5) as response:
    if json.load(response)["status"] != "ready":
        raise RuntimeError("Could not create a conversation.")
with client.open(
    urllib.request.Request(f"{BASE}/api/session", method="DELETE"), timeout=5
) as response:
    if json.load(response)["status"] != "cleared":
        raise RuntimeError("Could not clear a conversation.")
print("Container smoke check passed; no model or BigQuery request was made.")
