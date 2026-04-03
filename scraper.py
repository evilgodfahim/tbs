import requests
import sys
import os
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import re

FLARESOLVERR_URL = "http://localhost:8191/v1"

SOURCES = [
    {
        "name":       "latest",
        "url":        "https://www.tbsnews.net/latest",
        "xml_file":   "articles.xml",
        "feed_title": "The Business Standard - Latest",
        "site_link":  "https://www.tbsnews.net",
        "base_url":   "https://www.tbsnews.net",
        "scraper":    "tbs_en",
        "skip":       "/videos/",
    },
    {
        "name":       "thoughts",
        "url":        "https://www.tbsnews.net/thoughts",
        "xml_file":   "thoughts.xml",
        "feed_title": "The Business Standard - Thoughts",
        "site_link":  "https://www.tbsnews.net/thoughts",
        "base_url":   "https://www.tbsnews.net",
        "scraper":    "tbs_en",
        "skip":       "/videos/",
    },
    {
        "name":       "bangla",
        "url":        "https://www.tbsnews.net/bangla/",
        "xml_file":   "bangla.xml",
        "feed_title": "The Business Standard - বাংলা",
        "site_link":  "https://www.tbsnews.net/bangla/",
        "base_url":   "https://www.tbsnews.net",
        "scraper":    "tbs_bn",
        "skip":       "/bangla/video/",
    },
]

MAX_ITEMS = 500

# ---------------------------------------------------------------
# FETCH
# ---------------------------------------------------------------
def fetch_html(url):
    r = requests.post(FLARESOLVERR_URL, json={
        "cmd": "request.get",
        "url": url,
        "maxTimeout": 60000,
    }, timeout=90)
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"FlareSolverr error: {data['error']}")
    if "solution" not in data or "response" not in data["solution"]:
        raise RuntimeError(f"Invalid FlareSolverr response: {data}")
    return data["solution"]["response"]

# ---------------------------------------------------------------
# DATE
# ---------------------------------------------------------------
def parse_date(text):
    if not text:
        return datetime.now(timezone.utc)
    if "|" in text:
        text = text.split("|")[0].strip()
    text = text.strip()
    m = re.match(r"(\d+)\s*([mhd])", text.lower())
    if m:
        v, u = int(m.group(1)), m.group(2)
        delta = {"m": timedelta(minutes=v), "h": timedelta(hours=v), "d": timedelta(days=v)}[u]
        return datetime.now(timezone.utc) - delta
    try:
        dt = parsedate_to_datetime(text)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%b %d, %Y %I:%M %p", "%d %b %Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return datetime.now(timezone.utc)

# ---------------------------------------------------------------
# SCRAPERS
# ---------------------------------------------------------------
def scrape_tbs_en(soup, base_url, skip):
    articles, seen = [], set()
    for card in soup.select("div.card"):
        link_tag = card.select_one("h2.card-title a, h3.card-title a")
        if not link_tag:
            continue
        url = link_tag.get("href", "").strip()
        if not url:
            continue
        if url.startswith("/"):
            url = base_url + url
        if skip and skip in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        title = link_tag.get_text(strip=True)
        if not title:
            continue
        intro = card.select_one("p.card-intro")
        desc = intro.get_text(strip=True) if intro else ""
        date_tag = card.select_one("div.date")
        pub = parse_date(date_tag.get_text(strip=True) if date_tag else "")
        img_tag = card.select_one("img")
        img = ""
        if img_tag:
            img = img_tag.get("data-src", "") or img_tag.get("src", "")
            if img.startswith("/"):
                img = base_url + img
        articles.append({"url": url, "title": title, "desc": desc, "pub": pub, "img": img})
    return articles


def scrape_tbs_bn(soup, base_url, skip):
    articles, seen = [], set()
    for card in soup.select("div.card"):
        link_tag = (
            card.select_one("div.card-section h2 a")
            or card.select_one("div.card-section h3 a")
            or card.select_one("h2 a")
            or card.select_one("h3 a")
        )
        if not link_tag:
            continue
        url = link_tag.get("href", "").strip()
        if not url:
            continue
        if url.startswith("/"):
            url = base_url + url
        if skip and skip in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        title = link_tag.get_text(strip=True)
        if not title:
            continue
        desc = ""
        p_tag = card.select_one("p")
        if p_tag:
            desc = p_tag.get_text(strip=True)
        date_tag = card.select_one("div.date")
        pub = parse_date(date_tag.get_text(strip=True) if date_tag else "")
        img_tag = card.select_one("img")
        img = ""
        if img_tag:
            img = img_tag.get("data-src", "") or img_tag.get("src", "")
            if img.startswith("/"):
                img = base_url + img
        articles.append({"url": url, "title": title, "desc": desc, "pub": pub, "img": img})
    return articles


def scrape(html, source):
    soup = BeautifulSoup(html, "html.parser")
    if source["scraper"] == "tbs_bn":
        return scrape_tbs_bn(soup, source["base_url"], source["skip"])
    return scrape_tbs_en(soup, source["base_url"], source["skip"])

# ---------------------------------------------------------------
# XML UPDATE  (prepend new, recycle oldest beyond MAX_ITEMS)
# ---------------------------------------------------------------
def update_xml(articles, source):
    xml_file = source["xml_file"]

    if os.path.exists(xml_file):
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
        except ET.ParseError:
            root = ET.Element("rss", version="2.0")
    else:
        root = ET.Element("rss", version="2.0")

    channel = root.find("channel")
    if channel is None:
        channel = ET.SubElement(root, "channel")
        ET.SubElement(channel, "title").text       = source["feed_title"]
        ET.SubElement(channel, "link").text        = source["site_link"]
        ET.SubElement(channel, "description").text = source["feed_title"]

    existing = set()
    for item in channel.findall("item"):
        lt = item.find("link")
        if lt is not None and lt.text:
            existing.add(lt.text.strip())

    new_items = []
    for art in articles:
        if art["url"] in existing:
            continue
        el = ET.Element("item")
        ET.SubElement(el, "title").text       = art["title"]
        ET.SubElement(el, "link").text        = art["url"]
        ET.SubElement(el, "description").text = art["desc"]
        ET.SubElement(el, "pubDate").text     = art["pub"].strftime("%a, %d %b %Y %H:%M:%S %z")
        if art["img"]:
            ET.SubElement(el, "enclosure", url=art["img"], type="image/jpeg")
        new_items.append(el)

    # prepend new items after channel metadata tags
    insert_pos = sum(1 for c in channel if c.tag in ("title", "link", "description"))
    for i, el in enumerate(new_items):
        channel.insert(insert_pos + i, el)

    # recycle: drop oldest beyond MAX_ITEMS
    all_items = channel.findall("item")
    for old in all_items[MAX_ITEMS:]:
        channel.remove(old)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(xml_file, encoding="utf-8", xml_declaration=True)

    size = os.path.getsize(xml_file)
    print(f"  +{len(new_items)} new  |  {len(channel.findall('item'))} total  |  {size} bytes  →  {xml_file}")

# ---------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]
    source_filter = next((a.split("=")[1] for a in args if a.startswith("--source=")), None)

    for src in SOURCES:
        if source_filter and src["name"] != source_filter:
            continue
        print(f"\n[{src['name']}] {src['url']}")
        try:
            html     = fetch_html(src["url"])
            articles = scrape(html, src)
            print(f"  scraped {len(articles)} articles")
            if articles:
                update_xml(articles, src)
        except Exception as e:
            print(f"  ERROR: {e}")
