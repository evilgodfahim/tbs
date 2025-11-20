import requests
import json

FLARESOLVERR_URL = "http://localhost:8191/v1"
TARGET_URL = "https://samakal.com/opinion"

payload = {
    "cmd": "request.get",
    "url": TARGET_URL,
    "maxTimeout": 60000
}

response = requests.post(FLARESOLVERR_URL, json=payload)
data = response.json()

html = data["solution"]["response"]
with open("opinion.html", "w", encoding="utf-8") as f:
    f.write(html)
