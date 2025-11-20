import sys
import os
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from datetime import datetime

HTML_FILE = "opinion.html"
XML_FILE = "articles.xml"
MAX_ITEMS = 500

# Load HTML
if not os.path.exists(HTML_FILE):
    print("HTML not found")
    sys.exit(1)

with open(HTML_FILE, "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Parse article entries
articles = []

for a in soup.select("a[href*='/opinion/article/']"):
    url = a.get("href")

    # Title extraction
    h1 = a.select_one("h1")
    h3 = a.select_one("h3")
    title = None
    if h1:
        title = h1.get_text(strip=True)
    elif h3:
        title = h3.get_text(strip=True)
    else:
        continue

    # Description
    desc_tag = a.select_one("p")
    desc = desc_tag.get_text(strip=True) if desc_tag else ""

    # Publish time
    pub = ""
    t = a.select_one(".publishTime")
    if t:
        pub = t.get_text(strip=True)

    # Image
    img = ""
    img_tag = a.select_one("img")
    if img_tag:
        img = img_tag.get("src", "")

    articles.append({
        "url": url,
        "title": title,
        "desc": desc,
        "pub": pub,
        "img": img
    })

# Load previous XML or create new
if os.path.exists(XML_FILE):
    tree = ET.parse(XML_FILE)
    root = tree.getroot()
    channel = root.find("channel")
else:
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Samakal Opinion"
    ET.SubElement(channel, "link").text = "https://samakal.com/opinion"
    ET.SubElement(channel, "description").text = "Latest opinion articles from Samakal"

# Collect existing URLs
existing = set()
for item in channel.findall("item"):
    link_tag = item.find("link")
    if link_tag is not None:
        existing.add(link_tag.text.strip())

# Append new unique articles
for art in articles:
    if art["url"] in existing:
        continue

    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = art["title"]
    ET.SubElement(item, "link").text = art["url"]
    ET.SubElement(item, "description").text = art["desc"]
    ET.SubElement(item, "pubDate").text = art["pub"] if art["pub"] else datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    if art["img"]:
        ET.SubElement(item, "enclosure", url=art["img"], type="image/jpeg")

# Trim to last MAX_ITEMS
all_items = channel.findall("item")
if len(all_items) > MAX_ITEMS:
    # Remove oldest first
    for old_item in all_items[:-MAX_ITEMS]:
        channel.remove(old_item)

# Save XML
tree = ET.ElementTree(root)
tree.write(XML_FILE, encoding="utf-8", xml_declaration=True)