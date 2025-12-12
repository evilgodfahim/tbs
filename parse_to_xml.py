import sys
import os
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import json
import re

HTML_FILE = "news.html"
XML_FILE = "articles.xml"
DAILY_FILE_PREFIX = "daily_feed"
LAST_SEEN_FILE = "last_seen.json"

MAX_ITEMS = 500
MAX_ITEMS_PER_DAILY = 100  # Max items per daily feed file
BD_OFFSET = 6
LOOKBACK_HOURS = 48
LINK_RETENTION_DAYS = 7

# -----------------------------
# UTILITIES
# -----------------------------
def parse_relative_time(time_text):
    """Parse relative time like '32m', '1h', '2d' into datetime"""
    now = datetime.now(timezone.utc)
    time_text = time_text.strip().lower()
    
    # Match patterns like "32m", "1h", "2d"
    match = re.match(r'(\d+)\s*(m|h|d)', time_text)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        
        if unit == 'm':  # minutes
            return now - timedelta(minutes=value)
        elif unit == 'h':  # hours
            return now - timedelta(hours=value)
        elif unit == 'd':  # days
            return now - timedelta(days=value)
    
    return now

def parse_date_from_text(date_text):
    """Parse date from various formats"""
    if not date_text:
        return datetime.now(timezone.utc)
    
    # Try relative time first (like "32m", "1h")
    if re.match(r'\d+\s*[mhd]', date_text.strip().lower()):
        return parse_relative_time(date_text)
    
    try:
        # Try email format first
        dt = parsedate_to_datetime(date_text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    
    # Try common formats
    formats = [
        "%b %d, %Y %I:%M %p",  # Dec 12, 2025 01:27 PM
        "%d %b %Y %H:%M:%S",   # 12 Dec 2025 01:27:00
        "%Y-%m-%d %H:%M:%S",   # 2025-12-12 01:27:00
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    
    return datetime.now(timezone.utc)

def load_existing(file_path):
    """Load existing items from XML file"""
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
            title_node = item.find("title")
            link_node = item.find("link")
            desc_node = item.find("description")
            pub_node = item.find("pubDate")
            
            title = (title_node.text or "").strip() if title_node is not None else ""
            link = (link_node.text or "").strip() if link_node is not None else ""
            desc = desc_node.text or "" if desc_node is not None else ""
            
            if pub_node is not None and pub_node.text:
                dt = parse_date_from_text(pub_node.text)
            else:
                dt = datetime.now(timezone.utc)
            
            items.append({
                "title": title,
                "link": link,
                "description": desc,
                "pubDate": dt,
                "img": item.find("enclosure").get("url", "") if item.find("enclosure") is not None else ""
            })
        except Exception:
            continue
    return items

def write_rss(items, file_path, title="Feed"):
    """Write items to RSS XML file"""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = "https://www.tbsnews.net"
    ET.SubElement(channel, "description").text = f"{title} - The Business Standard News"

    for item in items:
        it = ET.SubElement(channel, "item")
        ET.SubElement(it, "title").text = item.get("title", "")
        ET.SubElement(it, "link").text = item.get("link", "")
        ET.SubElement(it, "description").text = item.get("description", "")
        
        pub = item.get("pubDate")
        if isinstance(pub, datetime):
            ET.SubElement(it, "pubDate").text = pub.strftime("%a, %d %b %Y %H:%M:%S %z")
        else:
            ET.SubElement(it, "pubDate").text = str(pub)
        
        if item.get("img"):
            ET.SubElement(it, "enclosure", url=item["img"], type="image/jpeg")

    xml_str = minidom.parseString(ET.tostring(rss)).toprettyxml(indent="  ")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(xml_str)

# -----------------------------
# LAST SEEN TRACKING
# -----------------------------
def load_last_seen():
    """Load last seen timestamp (no processed links tracking)"""
    if os.path.exists(LAST_SEEN_FILE):
        try:
            with open(LAST_SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_seen_str = data.get("last_seen")
                last_seen_dt = datetime.fromisoformat(last_seen_str) if last_seen_str else None
                return {"last_seen": last_seen_dt}
        except Exception:
            return {"last_seen": None}
    return {"last_seen": None}

def save_last_seen(last_dt):
    """Save only the last seen timestamp"""
    with open(LAST_SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "last_seen": last_dt.isoformat(),
            "last_run": datetime.now(timezone.utc).isoformat()
        }, f, indent=2)

# -----------------------------
# SCRAPE ARTICLES FROM HTML
# -----------------------------
def scrape_articles():
    """Extract articles from TBS (The Business Standard) HTML"""
    # Load HTML
    if not os.path.exists(HTML_FILE):
        print(f"HTML file '{HTML_FILE}' not found")
        return []

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    articles = []
    base_url = "https://www.tbsnews.net"

    # Extract articles from TBS format - looking for card containers
    for card in soup.select("div.card"):
        # Find the main article link
        link_tag = card.select_one("h3.card-title a")
        if not link_tag:
            continue
        
        url = link_tag.get("href", "")
        if not url:
            continue
        
        # Make URL absolute if needed
        if url.startswith("/"):
            url = base_url + url
        
        # EXCLUDE video links
        if "/videos/" in url:
            print(f"Skipping video link: {url}")
            continue
        
        # Get title
        title = link_tag.get_text(strip=True)
        if not title:
            continue
        
        # Get description - not present in this format, use empty string
        desc = ""
        
        # Get publication date from the date div
        date_tag = card.select_one("div.date")
        pub_text = date_tag.get_text(strip=True) if date_tag else ""
        pub_date = parse_date_from_text(pub_text)
        
        # Get image
        img = ""
        img_tag = card.select_one("img")
        if img_tag:
            # Try data-src first (lazy loaded), then src
            img = img_tag.get("data-src", "") or img_tag.get("src", "")
            # Make image URL absolute if needed
            if img and img.startswith("/"):
                img = base_url + img
        
        articles.append({
            "url": url,
            "title": title,
            "desc": desc,
            "pub": pub_date,
            "img": img
        })

    print(f"Found {len(articles)} articles in HTML (excluding videos)")
    return articles

# -----------------------------
# UPDATE MAIN XML FILE
# -----------------------------
def update_main_xml():
    """Update the main articles.xml file"""
    print("[Updating articles.xml]")
    
    articles = scrape_articles()
    if not articles:
        print("No articles found in HTML")
        return
    
    # Load existing XML
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
        ET.SubElement(channel, "title").text = "The Business Standard News"
        ET.SubElement(channel, "link").text = "https://www.tbsnews.net"
        ET.SubElement(channel, "description").text = "Latest news articles from The Business Standard Bangladesh"

    # Deduplicate existing URLs
    existing = set()
    for item in channel.findall("item"):
        link_tag = item.find("link")
        if link_tag is not None:
            existing.add(link_tag.text.strip())

    # Create new items for unique articles
    new_items = []
    new_count = 0
    for art in articles:
        if art["url"] in existing:
            continue
        
        item = ET.Element("item")
        ET.SubElement(item, "title").text = art["title"]
        ET.SubElement(item, "link").text = art["url"]
        ET.SubElement(item, "description").text = art["desc"]
        ET.SubElement(item, "pubDate").text = art["pub"].strftime("%a, %d %b %Y %H:%M:%S %z")
        
        if art["img"]:
            ET.SubElement(item, "enclosure", url=art["img"], type="image/jpeg")
        
        existing.add(art["url"])
        new_items.append(item)
        new_count += 1

    # Insert new items at the top of the channel
    insert_position = 0
    for child in channel:
        if child.tag in ["title", "link", "description"]:
            insert_position += 1
        else:
            break

    for i, item in enumerate(new_items):
        channel.insert(insert_position + i, item)

    print(f"Added {new_count} new articles at the top")

    # Trim to last MAX_ITEMS
    all_items = channel.findall("item")
    if len(all_items) > MAX_ITEMS:
        removed = len(all_items) - MAX_ITEMS
        for old_item in all_items[MAX_ITEMS:]:
            channel.remove(old_item)
        print(f"Removed {removed} old articles (keeping last {MAX_ITEMS})")

    # Save XML with proper formatting
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(XML_FILE, encoding="utf-8", xml_declaration=True)

    print(f"✓ {XML_FILE} saved successfully")
    print(f"✓ File path: {os.path.abspath(XML_FILE)}")
    print(f"Total articles in feed: {len(channel.findall('item'))}")

# -----------------------------
# UPDATE DAILY FEED
# -----------------------------
def update_daily():
    """Update daily feed with articles published since last run"""
    print("\n[Updating daily_feed.xml - Fresh articles only]")
    to_zone = timezone(timedelta(hours=BD_OFFSET))

    last_data = load_last_seen()
    last_seen_dt = last_data["last_seen"]

    # If first run, use lookback window
    if last_seen_dt:
        # Only get articles published AFTER last run
        cutoff_dt = last_seen_dt
    else:
        # First run: get articles from last 24 hours
        cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=24)

    master_items = load_existing(XML_FILE)
    new_items = []
    seen_links = set()  # Deduplicate within this batch

    for item in master_items:
        link = item["link"]
        pub = item["pubDate"]

        # Skip duplicates within this batch
        if link in seen_links:
            continue

        # Only include articles published after cutoff
        if pub > cutoff_dt:
            new_items.append(item)
            seen_links.add(link)

    if not new_items:
        placeholder = [{
            "title": "No new articles since last update",
            "link": "https://www.tbsnews.net",
            "description": "Daily feed will populate when new articles are published.",
            "pubDate": datetime.now(timezone.utc),
            "img": ""
        }]

        # Create empty daily_feed.xml
        write_rss(placeholder, f"{DAILY_FILE_PREFIX}.xml", title="Daily Feed - The Business Standard")
        
        # Update last_seen to current time
        save_last_seen(datetime.now(timezone.utc))
        print("✓ No new articles for daily feed")
        print(f"✓ {DAILY_FILE_PREFIX}.xml saved (placeholder)")
        return [f"{DAILY_FILE_PREFIX}.xml"]

    new_items.sort(key=lambda x: x["pubDate"], reverse=True)

    # Split into batches of MAX_ITEMS_PER_DAILY
    batches = []
    for i in range(0, len(new_items), MAX_ITEMS_PER_DAILY):
        batches.append(new_items[i:i + MAX_ITEMS_PER_DAILY])

    # Create files for each batch
    created_files = []
    for idx, batch in enumerate(batches):
        if idx == 0:
            filename = f"{DAILY_FILE_PREFIX}.xml"
            title = "Daily Feed - The Business Standard"
        else:
            filename = f"{DAILY_FILE_PREFIX}_{idx + 1}.xml"
            title = f"Daily Feed {idx + 1} - The Business Standard"
        
        write_rss(batch, filename, title=title)
        created_files.append(filename)
        print(f"✓ {filename} saved with {len(batch)} articles")
        print(f"✓ File path: {os.path.abspath(filename)}")

    # Save the latest publication date as last_seen
    last_dt = max([i["pubDate"] for i in new_items])
    save_last_seen(last_dt)
    print(f"✓ {LAST_SEEN_FILE} saved successfully")
    print(f"✓ File path: {os.path.abspath(LAST_SEEN_FILE)}")
    print(f"✓ Processed {len(new_items)} new articles across {len(batches)} file(s)")
    print(f"✓ Last seen date: {last_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    return created_files

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    args = sys.argv[1:]
    
    print("=" * 60)
    print("The Business Standard Article Scraper")
    print("=" * 60)
    
    files_created = []
    
    if "--daily-only" in args:
        daily_files = update_daily()
        files_created = daily_files + [LAST_SEEN_FILE]
    elif "--main-only" in args:
        update_main_xml()
        files_created = [XML_FILE]
    else:
        # Default: update both
        update_main_xml()
        daily_files = update_daily()
        files_created = [XML_FILE] + daily_files + [LAST_SEEN_FILE]
    
    print("\n" + "=" * 60)
    print("FILES CREATED/UPDATED:")
    print("=" * 60)
    for f in files_created:
        exists = "✓ EXISTS" if os.path.exists(f) else "✗ NOT FOUND"
        size = os.path.getsize(f) if os.path.exists(f) else 0
        print(f"{exists} | {f} ({size} bytes)")
    
    print("\n✓ All operations completed!")
    print("=" * 60)
