import requests
from bs4 import BeautifulSoup
import json
import hashlib
import re
import time
import os
from PIL import Image, ImageDraw
from io import BytesIO

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://cakhiatv247.net/"
}

BASE_URL = "https://cakhiatv247.net"
CBOX_URL = "https://cbox-v2.cakhiatv89.com/"
THUMBS_DIR = "thumbs"
REPO_RAW = os.environ.get("REPO_RAW", "")  # Set trong workflow

def make_id(text, prefix):
    h = hashlib.md5(text.encode()).hexdigest()[:10]
    return f"{prefix}-{h}"

def fetch_image(url):
    """Tải ảnh từ URL, trả về PIL Image hoặc None"""
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        return Image.open(BytesIO(res.content)).convert("RGBA")
    except:
        return None

def make_thumbnail(logo_a_url, logo_b_url, channel_id):
    """Ghép 2 logo thành thumbnail 800x600, lưu vào thumbs/"""
    os.makedirs(THUMBS_DIR, exist_ok=True)
    out_path = f"{THUMBS_DIR}/{channel_id}.png"

    # Nếu đã có file thì dùng lại
    if os.path.exists(out_path):
        return out_path

    W, H = 800, 500
    bg = Image.new("RGBA", (W, H), (15, 23, 42, 255))  # #0f172a
    draw = ImageDraw.Draw(bg)

    logo_size = 180

    # Logo A (trái)
    if logo_a_url:
        img_a = fetch_image(logo_a_url)
        if img_a:
            img_a = img_a.resize((logo_size, logo_size), Image.LANCZOS)
            x = W // 4 - logo_size // 2
            y = H // 2 - logo_size // 2
            bg.paste(img_a, (x, y), img_a)

    # VS ở giữa
    draw.text((W//2, H//2), "VS", fill=(255,255,255,200), anchor="mm")

    # Logo B (phải)
    if logo_b_url:
        img_b = fetch_image(logo_b_url)
        if img_b:
            img_b = img_b.resize((logo_size, logo_size), Image.LANCZOS)
            x = W * 3 // 4 - logo_size // 2
            y = H // 2 - logo_size // 2
            bg.paste(img_b, (x, y), img_b)

    # Convert sang RGB để lưu PNG
    final = bg.convert("RGB")
    final.save(out_path, "PNG", optimize=True)
    return out_path

def get_matches():
    res = requests.get(BASE_URL, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(res.text, "html.parser")

    matches = []
    seen = set()

    for card in soup.select("div.grid-matches__item"):
        a_tag = card.select_one("a[href*='/truc-tiep/']")
        if not a_tag:
            continue
        href = a_tag.get("href", "")
        if not href or href in seen:
            continue
        seen.add(href)

        url = BASE_URL + href if href.startswith("/") else href
        match_id = re.search(r'/(\d+)(?:\?|$)', href)
        if not match_id:
            continue
        match_id = match_id.group(1)

        card_class = " ".join(card.get("class", []))
        is_live = "stream_m_live" in card_class

        SKIP_ALTS = {"","Bóng đá","Bóng rổ","Cầu Lông","Tennis","Billiards","Võ Thuật","Bóng chuyền","Pickleball"}
        team_imgs = [
            i for i in card.select("img[width='64']")
            if i.get("alt","").strip() and i.get("alt","") not in SKIP_ALTS
        ]
        logo_a, logo_b, team_a, team_b = "", "", "", ""
        if len(team_imgs) >= 1:
            logo_a = team_imgs[0].get("data-src") or team_imgs[0].get("src","")
            team_a = team_imgs[0].get("alt","")
        if len(team_imgs) >= 2:
            logo_b = team_imgs[1].get("data-src") or team_imgs[1].get("src","")
            team_b = team_imgs[1].get("alt","")

        league_tag = card.select_one("span.s_by_name")
        league = league_tag.get_text(strip=True) if league_tag else ""

        time_tag = card.select_one("span.font-mono")
        match_time = time_tag.get_text(strip=True) if time_tag else ""

        blv_list = []
        for blv_a in card.select("a[href*='?blv=']"):
            blv_href = blv_a.get("href", "")
            blv_id_m = re.search(r'\?blv=(\d+)', blv_href)
            blv_name = blv_a.get_text(strip=True)
            if blv_id_m and blv_name:
                blv_list.append({"id": blv_id_m.group(1), "name": blv_name})

        name = f"{team_a} vs {team_b}" if team_a and team_b else href.split("/")[2][:50]

        matches.append({
            "url": url,
            "match_id": match_id,
            "name": name,
            "time": match_time,
            "team_a": team_a,
            "team_b": team_b,
            "logo_a": logo_a,
            "logo_b": logo_b,
            "league": league,
            "is_live": is_live,
            "blv_list": blv_list,
        })

    return matches

def get_streams(match_id, blv_list):
    streams = []
    channel_ids = [b["id"] for b in blv_list] if blv_list else ["0"]

    for ch_id in channel_ids[:3]:
        try:
            url = f"{CBOX_URL}?match_id={match_id}&channel_id={ch_id}"
            res = requests.get(url, headers=HEADERS, timeout=10)
            found = re.findall(r'https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*', res.text)
            for lnk in found:
                clean = lnk.replace("\\u0026", "&").replace("\\/", "/")
                if clean not in streams:
                    streams.append(clean)
            if streams:
                break
        except Exception as e:
            print(f"    Loi cbox {match_id}/{ch_id}: {e}")
        time.sleep(0.2)

    return streams

def build_channel(match, streams, thumb_url=""):
    uid    = make_id(match["url"], "kaytee")
    src_id = make_id(match["url"], "src")
    ct_id  = make_id(match["url"], "ct")
    st_id  = make_id(match["url"], "st")

    stream_links = []
    for i, s_url in enumerate(streams):
        lnk_id = make_id(s_url + str(i), "lnk")
        stream_links.append({
            "id": lnk_id,
            "name": f"Link {i+1}",
            "type": "hls",
            "default": i == 0,
            "url": s_url,
            "request_headers": [
                {"key": "Referer", "value": "https://cakhiatv247.net/"},
                {"key": "User-Agent", "value": "Mozilla/5.0"}
            ]
        })

    blv_names = ", ".join([b["name"] for b in match["blv_list"]]) if match["blv_list"] else ""
    display_name = match["name"]
    if match["time"]:
        display_name = f"{match['name']} ({match['time']})"

    label_text  = "● LIVE" if match["is_live"] else f"🕐 {match['time']}"
    label_color = "#ff4444" if match["is_live"] else "#aaaaaa"

    channel = {
        "id": uid,
        "name": display_name,
        "type": "single",
        "display": "thumbnail-only",
        "enable_detail": False,
        "labels": [{"text": label_text, "position": "top-left",
                    "color": "#00000080", "text_color": label_color}],
        "sources": [{
            "id": src_id,
            "name": "CakhiaTV",
            "contents": [{
                "id": ct_id,
                "name": match["name"],
                "streams": [{"id": st_id, "name": "KT", "stream_links": stream_links}]
            }]
        }],
        "org_metadata": {
            "league": match.get("league", ""),
            "team_a": match.get("team_a", ""),
            "team_b": match.get("team_b", ""),
            "logo_a": match.get("logo_a", ""),
            "logo_b": match.get("logo_b", ""),
            "time": match.get("time", ""),
            "blv": blv_names,
            "is_live": match["is_live"],
        }
    }

    # Thêm thumbnail nếu có
    if thumb_url:
        channel["image"] = {
            "padding": 4,
            "background_color": "#0f172a",
            "display": "contain",
            "url": thumb_url,
            "width": 800,
            "height": 500
        }

    return channel

def main():
    print("Lay danh sach tran tu cakhiatv247...")
    matches = get_matches()

    live_matches     = [m for m in matches if m["is_live"]]
    upcoming_matches = [m for m in matches if not m["is_live"]]

    print(f"Tong: {len(matches)} | LIVE: {len(live_matches)} | Sap: {len(upcoming_matches)}\n")

    live_channels     = []
    upcoming_channels = []

    for i, match in enumerate(live_matches):
        print(f"[LIVE {i+1}/{len(live_matches)}] {match['name']}")
        streams = get_streams(match["match_id"], match["blv_list"])
        print(f"  stream: {len(streams)} link")
        if not streams:
            continue

        # Tạo thumbnail
        uid = make_id(match["url"], "kaytee")
        thumb_path = make_thumbnail(match["logo_a"], match["logo_b"], uid)
        thumb_url = f"{REPO_RAW}/{thumb_path}" if REPO_RAW else ""
        print(f"  thumb: {thumb_path}")

        live_channels.append(build_channel(match, streams, thumb_url))
        time.sleep(0.3)

    for match in upcoming_matches:
        uid = make_id(match["url"], "kaytee")
        thumb_path = make_thumbnail(match["logo_a"], match["logo_b"], uid)
        thumb_url = f"{REPO_RAW}/{thumb_path}" if REPO_RAW else ""
        upcoming_channels.append(build_channel(match, [], thumb_url))

    groups = []
    if live_channels:
        groups.append({
            "id": "live", "name": "🔴 Đang Live",
            "display": "vertical", "grid_number": 2,
            "enable_detail": False, "channels": live_channels
        })
    if upcoming_channels:
        groups.append({
            "id": "upcoming", "name": "🕐 Sắp Diễn Ra",
            "display": "vertical", "grid_number": 2,
            "enable_detail": False, "channels": upcoming_channels
        })

    output = {
        "id": "cakhia",
        "url": "https://cakhiatv247.net",
        "name": "CakhiaTV",
        "color": "#1cb57a",
        "grid_number": 3,
        "image": {"type": "cover", "url": "https://cakhiatv247.net/img/logo-247-1.png"},
        "groups": groups
    }

    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nXong! LIVE: {len(live_channels)} | Sap: {len(upcoming_channels)} -> output.json")

if __name__ == "__main__":
    main()
