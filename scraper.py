import requests
import sys
import os
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import json
import re

# ---------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------
FLARESOLVERR_URL = "http://localhost:8191/v1"

SOURCES = [
    {
        "name":           "latest",
        "url":            "https://www.tbsnews.net/latest",
        "xml_file":       "articles.xml",
        "daily_prefix":   "daily_feed",
        "last_seen_file": "last_seen.json",
        "feed_title":     "The Business Standard - Latest",
        "site_link":      "https://www.tbsnews.net",
        "base_url":       "https://www.tbsnews.net",
        "scraper":        "tbs_en",
        "skip_pattern":   "/videos/",
    },
    {
        "name":           "thoughts",
        "url":            "https://www.tbsnews.net/thoughts",
        "xml_file":       "thoughts_articles.xml",
        "daily_prefix":   "thoughts_daily_feed",
        "last_seen_file": "thoughts_last_seen.json",
        "feed_title":     "The Business Standard - Thoughts",
        "site_link":      "https://www.tbsnews.net/thoughts",
        "base_url":       "https://www.tbsnews.net",
        "scraper":        "tbs_en",
        "skip_pattern":   "/videos/",
    },
    {
        "name":           "bangla",
        "url":            "https://www.tbsnews.net/bangla/",
        "xml_file":       "bangla_articles.xml",
        "daily_prefix":   "bangla_daily_feed",
        "last_seen_file": "bangla_last_seen.json",
        "feed_title":     "The Business Standard - বাংলা",
        "site_link":      "https://www.tbsnews.net/bangla/",
        "base_url":       "https://www.tbsnews.net",
        "scraper":        "tbs_bn",
        "skip_pattern":   "/bangla/video/",
    },
]

MAX_ITEMS           = 1000
MAX_ITEMS_PER_DAILY = 100

# ---------------------------------------------------------------
# FETCH via FlareSolverr
# ---------------------------------------------------------------
def fetch_html(target_url):
    payload = {
        "cmd":        "request.get",
        "url":        target_url,
        "maxTimeout": 60000,
    }
    r = requests.post(FLARESOLVERR_URL, json=payload, timeout=90)
    data = r.json()

    if "error" in data:
        raise RuntimeError(f"FlareSolverr error for {target_url}: {data['error']}")

    if "solution" not in data or "response" not in data["solution"]:
        raise RuntimeError(f"Invalid FlareSolverr response for {target_url}: {data}")

    return data["solution"]["response"]

# ---------------------------------------------------------------
# DATE HELPERS
# ---------------------------------------------------------------
def parse_relative_time(time_text):
    now = datetime.now(timezone.utc)
    time_text = time_text.strip().lower()
    match = re.match(r"(\d+)\s*([mhd])", time_text)
    if match:
        value = int(match.group(1))
        unit  = match.group(2)
        if unit == "m":
            return now - timedelta(minutes=value)
        elif unit == "h":
            return now - timedelta(hours=value)
        elif unit == "d":
            return now - timedelta(days=value)
    return now

def parse_date_from_text(date_text):
    if not date_text:
        return datetime.now(timezone.utc)

    # strip pipe-separated category suffix, e.g. "4h | আন্তর্জাতিক"
    if "|" in date_text:
        date_text = date_text.split("|")[0].strip()

    if re.match(r"\d+\s*[mhd]", date_text.strip().lower()):
        return parse_relative_time(date_text)

    try:
        dt = parsedate_to_datetime(date_text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    for fmt in ("%b %d, %Y %I:%M %p", "%d %b %Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue

    return datetime.now(timezone.utc)

# ---------------------------------------------------------------
# SCRAPERS
# ---------------------------------------------------------------
def scrape_tbs_en(soup, base_url, skip_pattern):
    """Handles /latest and /thoughts — same card structure."""
    articles = []
    seen = set()
    for card in soup.select("div.card"):
        link_tag = card.select_one("h2.card-title a, h3.card-title a")
        if not link_tag:
            continue
        url = link_tag.get("href", "").strip()
        if not url:
            continue
        if url.startswith("/"):
            url = base_url + url
        if skip_pattern and skip_pattern in url:
            continue
        if url in seen:
            continue
        seen.add(url)

        title = link_tag.get_text(strip=True)
        if not title:
            continue

        desc = ""
        intro = card.select_one("p.card-intro")
        if intro:
            desc = intro.get_text(strip=True)

        date_tag = card.select_one("div.date")
        pub_date = parse_date_from_text(date_tag.get_text(strip=True) if date_tag else "")

        img = ""
        img_tag = card.select_one("img")
        if img_tag:
            img = img_tag.get("data-src", "") or img_tag.get("src", "")
            if img and img.startswith("/"):
                img = base_url + img

        articles.append({"url": url, "title": title, "desc": desc, "pub": pub_date, "img": img})

    return articles


def scrape_tbs_bn(soup, base_url, skip_pattern):
    """Handles /bangla/ homepage — varied card layouts."""
    articles = []
    seen = set()
    for card in soup.select("div.card"):
        # title link can be in h2 or h3 inside card-section, or directly in card
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
        if skip_pattern and skip_pattern in url:
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
        pub_date = parse_date_from_text(date_tag.get_text(strip=True) if date_tag else "")

        img = ""
        img_tag = card.select_one("img")
        if img_tag:
            img = img_tag.get("data-src", "") or img_tag.get("src", "")
            if img and img.startswith("/"):
                img = base_url + img

        articles.append({"url": url, "title": title, "desc": desc, "pub": pub_date, "img": img})

    return articles


def scrape_html(html, source):
    soup = BeautifulSoup(html, "html.parser")
    base_url     = source["base_url"]
    skip_pattern = source.get("skip_pattern", "")
    if source["scraper"] == "tbs_bn":
        return scrape_tbs_bn(soup, base_url, skip_pattern)
    else:
        return scrape_tbs_en(soup, base_url, skip_pattern)

# ---------------------------------------------------------------
# XML HELPERS
# ---------------------------------------------------------------
def load_existing_xml(file_path):
    """Return list of dicts from an existing RSS XML file."""
    if not os.path.exists(file_path):
        return []
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except Exception:
        return []

    items = []
    for item in root.findall(".//item"):
        try:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link")  or "").strip()
            desc  = item.findtext("description") or ""
            pub   = item.findtext("pubDate") or ""
            dt    = parse_date_from_text(pub) if pub else datetime.now(timezone.utc)
            enc   = item.find("enclosure")
            img   = enc.get("url", "") if enc is not None else ""
            items.append({"title": title, "link": link, "description": desc, "pubDate": dt, "img": img})
        except Exception:
            continue
    return items


def write_rss(items, file_path, source):
    rss     = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text       = source["feed_title"]
    ET.SubElement(channel, "link").text        = source["site_link"]
    ET.SubElement(channel, "description").text = source["feed_title"]

    for item in items:
        it = ET.SubElement(channel, "item")
        ET.SubElement(it, "title").text       = item.get("title", "")
        ET.SubElement(it, "link").text        = item.get("link", "")
        ET.SubElement(it, "description").text = item.get("description", "")
        pub = item.get("pubDate")
        ET.SubElement(it, "pubDate").text = (
            pub.strftime("%a, %d %b %Y %H:%M:%S %z") if isinstance(pub, datetime) else str(pub)
        )
        if item.get("img"):
            ET.SubElement(it, "enclosure", url=item["img"], type="image/jpeg")

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ", level=0)
    tree.write(file_path, encoding="utf-8", xml_declaration=True)

# ---------------------------------------------------------------
# LAST-SEEN TRACKING
# ---------------------------------------------------------------
def load_last_seen(path):
    if not os.path.exists(path):
        return {"last_seen": None, "seen_links": set()}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        last_dt    = datetime.fromisoformat(data["last_seen"]) if data.get("last_seen") else None
        seen_links = set(data.get("seen_links", []))
        return {"last_seen": last_dt, "seen_links": seen_links}
    except Exception:
        return {"last_seen": None, "seen_links": set()}


def save_last_seen(path, last_dt, seen_links):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "last_seen":  last_dt.isoformat() if last_dt else None,
            "seen_links": list(seen_links),
            "last_run":   datetime.now(timezone.utc).isoformat(),
        }, f, indent=2)

# ---------------------------------------------------------------
# MAIN XML UPDATE
# ---------------------------------------------------------------
def update_main_xml(articles, source):
    xml_file = source["xml_file"]
    print(f"  [main xml] → {xml_file}")

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
        item = ET.Element("item")
        ET.SubElement(item, "title").text       = art["title"]
        ET.SubElement(item, "link").text        = art["url"]
        ET.SubElement(item, "description").text = art["desc"]
        ET.SubElement(item, "pubDate").text     = art["pub"].strftime("%a, %d %b %Y %H:%M:%S %z")
        if art["img"]:
            ET.SubElement(item, "enclosure", url=art["img"], type="image/jpeg")
        existing.add(art["url"])
        new_items.append(item)

    # Insert new items just after channel metadata
    insert_pos = sum(1 for c in channel if c.tag in ("title", "link", "description"))
    for i, item in enumerate(new_items):
        channel.insert(insert_pos + i, item)

    # Trim to MAX_ITEMS
    all_items = channel.findall("item")
    for old in all_items[MAX_ITEMS:]:
        channel.remove(old)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(xml_file, encoding="utf-8", xml_declaration=True)
    print(f"  Added {len(new_items)} new items to {xml_file}")

# ---------------------------------------------------------------
# DAILY FEED UPDATE
# ---------------------------------------------------------------
def update_daily(source):
    prefix         = source["daily_prefix"]
    last_seen_file = source["last_seen_file"]
    xml_file       = source["xml_file"]
    print(f"  [daily feed] prefix={prefix}")

    last_data  = load_last_seen(last_seen_file)
    seen_links = set(last_data["seen_links"])

    master_items = load_existing_xml(xml_file)
    new_items    = [i for i in master_items if i["link"] not in seen_links]
    for i in new_items:
        seen_links.add(i["link"])

    if not new_items:
        placeholder = [{
            "title":       "No new articles since last update",
            "link":        source["site_link"],
            "description": "Daily feed will populate when new articles are published.",
            "pubDate":     datetime.now(timezone.utc),
            "img":         "",
        }]
        write_rss(placeholder, f"{prefix}.xml", source)
        save_last_seen(last_seen_file, datetime.now(timezone.utc), seen_links)
        return [f"{prefix}.xml", last_seen_file]

    new_items.sort(key=lambda x: x["pubDate"], reverse=True)

    created = []
    for idx, batch in enumerate(
        new_items[i : i + MAX_ITEMS_PER_DAILY]
        for i in range(0, len(new_items), MAX_ITEMS_PER_DAILY)
    ):
        filename = f"{prefix}.xml" if idx == 0 else f"{prefix}_{idx + 1}.xml"
        feed_title = source["feed_title"] + (f" {idx + 1}" if idx else "")
        src_copy = dict(source, feed_title=feed_title)
        write_rss(batch, filename, src_copy)
        created.append(filename)
        print(f"  Written {len(batch)} items → {filename}")

    last_dt = max(i["pubDate"] for i in new_items)
    save_last_seen(last_seen_file, last_dt, seen_links)
    return created + [last_seen_file]

# ---------------------------------------------------------------
# PROCESS ONE SOURCE
# ---------------------------------------------------------------
def process_source(source, mode):
    print(f"\n=== [{source['name']}] {source['url']} ===")
    created_files = []

    if mode in ("main", "both"):
        print(f"  Fetching HTML…")
        html     = fetch_html(source["url"])
        articles = scrape_html(html, source)
        print(f"  Scraped {len(articles)} articles")
        if not articles:
            print("  No articles found, skipping.")
        else:
            update_main_xml(articles, source)
            created_files.append(source["xml_file"])

    if mode in ("daily", "both"):
        daily_files = update_daily(source)
        created_files.extend(daily_files)

    return created_files

# ---------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------
if __name__ == "__main__":
    args = sys.argv[1:]

    if "--daily-only" in args:
        mode = "daily"
    elif "--main-only" in args:
        mode = "main"
    else:
        mode = "both"

    # Optional: filter to a single source with --source=latest|thoughts|bangla
    source_filter = next((a.split("=")[1] for a in args if a.startswith("--source=")), None)

    all_files = []
    for src in SOURCES:
        if source_filter and src["name"] != source_filter:
            continue
        try:
            files = process_source(src, mode)
            all_files.extend(files)
        except Exception as e:
            print(f"  ERROR processing {src['name']}: {e}")

    print("\n--- Output files ---")
    for f in all_files:
        exists = "✓" if os.path.exists(f) else "✗"
        size   = os.path.getsize(f) if os.path.exists(f) else 0
        print(f"{exists} {f} ({size} bytes)")
