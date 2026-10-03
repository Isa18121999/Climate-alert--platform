import os
import requests

API_URL = os.getenv("API_URL", "https://climate-alert-platform-api.onrender.com").rstrip("/")
r = requests.get(API_URL + "/monitor", timeout=60)
r.raise_for_status()
print(r.text)
