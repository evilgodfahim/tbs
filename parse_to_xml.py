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

articles = []

# --- 1. DCatLead (main lead) ---
for lead in soup.select("div.DCatLead a[href*='/opinion/article/']"):
    url = lead.get("href")
    h1 = lead.select_one("h1")
    title = h1.get_text(strip=True) if h1 else None
    if not title:
        continue
    desc_tag = lead.select_one("p.CatDesc")
    desc = desc_tag.get_text(strip=True) if desc_tag else ""
    pub_tag = lead.select_one(".publishTime")
    pub = pub_tag.get_text(strip=True) if pub_tag else ""
    img_tag = lead.select_one("img")
    img = img_tag.get("src", "") if img_tag else ""
    articles.append({"url": url, "title": title, "desc": desc, "pub": pub, "img": img})

# --- 2. Catcards (category cards) ---
for card in soup.select("div.Catcards a[href*='/opinion/article/']"):
    url = card.get("href")
    h3 = card.select_one("h3")
    title = h3.get_text(strip=True) if h3 else None
    if not title:
        continue
    desc_tag = card.select_one("p")
    desc = desc_tag.get_text(strip=True) if desc_tag else ""
    pub_tag = card.select_one(".publishTime")
    pub = pub_tag.get_text(strip=True) if pub_tag else ""
    img_tag = card.select_one("img")
    img = img_tag.get("src", "") if img_tag else ""
    articles.append({"url": url, "title": title, "desc": desc, "pub": pub, "img": img})

# --- 3. CatListNews (sub news) ---
for sub in soup.select("div.CatListNews a[href*='/opinion/article/']"):
    url = sub.get("href")
    h3 = sub.select_one("h3")
    title = h3.get_text(strip=True) if h3 else None
    if not title:
        continue
    desc_tag = sub.select_one("p")
    desc = desc_tag.get_text(strip=True) if desc_tag else ""
    pub_tag = sub.select_one(".publishTime")
    pub = pub_tag.get_text(strip=True) if pub_tag else ""
    img_tag = sub.select_one("img")
    img = img_tag.get("src", "") if img_tag else ""
    articles.append({"url": url, "title": title, "desc": desc, "pub": pub, "img": img})

# --- Load or create XML ---
if os.path.exists(XML_FILE):
    try:
        tree = ET.parse(XML_FILE)
        root = tree.getroot()
    except ET.ParseError:
        root = ET.Element("rss", version="2.0")
else:
    root = ET.Element("rss", version="2.0")

# Ensure channel exists
channel = root.find("channel")
if channel is None:
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Samakal Opinion"
    ET.SubElement(channel, "link").text = "https://samakal.com/opinion"
    ET.SubElement(channel, "description").text = "Latest opinion articles from Samakal"

# Deduplicate existing URLs
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
    for old_item in all_items[:-MAX_ITEMS]:
        channel.remove(old_item)

# Save XML
tree = ET.ElementTree(root)
tree.write(XML_FILE, encoding="utf-8", xml_declaration=True)