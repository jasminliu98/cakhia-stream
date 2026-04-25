import requests
from bs4 import BeautifulSoup
import json
import hashlib
import re
import time
import os
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://cakhiatv247.net/"
}

BASE_URL = "https://cakhiatv247.net"
CBOX_URL = "https://cbox-v2.cakhiatv89.com/"
THUMBS_DIR = "thumbs"
REPO_RAW = os.environ.get("REPO_RAW", "")

# Map icon-cate sang tên môn (lấy từ HTML thực tế)
# FIX 1: Thêm Billiards (4) và Bóng chuyền (50)
CATE_MAP = {
    "1":  "⚽ Bóng Đá",
    "2":  "🥊 Võ Thuật",
    "4":  "🎱 Billiards",
    "13": "🏸 Cầu Lông",
    "20": "🏀 Bóng Rổ",
    "27": "🎾 Tennis",
    "50": "🏐 Bóng Chuyền",
}

def make_id(text, prefix):
    h = hashlib.md5(text.encode()).hexdigest()[:10]
    return f"{prefix}-{h}"

def fetch_image(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        return Image.open(BytesIO(res.content)).convert("RGBA")
    except:
        return None

THUMB_VERSION = "v3"  # Tăng version này để force regenerate tất cả thumbnail cũ

def make_thumbnail(match, channel_id):
    os.makedirs(THUMBS_DIR, exist_ok=True)
    # Dùng cả nội dung + version để cache bust khi layout thay đổi
    cache_key = match.get("logo_a","") + match.get("logo_b","") + THUMB_VERSION
    logo_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
    out_path = f"{THUMBS_DIR}/{channel_id}_{logo_hash}.png"

    W, H = 1600, 1200

    # Nền trắng
    bg = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(bg)

    # Viền xám nhạt
    draw.rectangle([(0,0),(W-1,H-1)], outline=(220,220,220), width=4)

    # Header: giải đấu (nền xanh đậm)
    draw.rectangle([(0,0),(W,120)], fill=(15, 23, 42))

    # Footer: BLV (nền xanh đậm)
    draw.rectangle([(0, H-100),(W, H)], fill=(15, 23, 42))

    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font_vs    = ImageFont.truetype(FONT_BOLD, 130)
        font_time  = ImageFont.truetype(FONT_BOLD, 80)
        font_team  = ImageFont.truetype(FONT_BOLD, 55)
        font_league= ImageFont.truetype(FONT_BOLD, 52)
        font_blv   = ImageFont.truetype(FONT_BOLD, 52)  # Bold, cùng size league
    except:
        font_vs = font_time = font_team = font_league = font_blv = ImageFont.load_default()

    logo_size = 320
    logo_y = 145  # sát header hơn để nhường chỗ phía dưới

    # Logo A (trái)
    if match.get("logo_a"):
        img_a = fetch_image(match["logo_a"])
        if img_a:
            img_a = img_a.resize((logo_size, logo_size), Image.LANCZOS)
            x = W//4 - logo_size//2
            bg.paste(img_a, (x, logo_y), img_a)

    # Logo B (phải)
    if match.get("logo_b"):
        img_b = fetch_image(match["logo_b"])
        if img_b:
            img_b = img_b.resize((logo_size, logo_size), Image.LANCZOS)
            x = W*3//4 - logo_size//2
            bg.paste(img_b, (x, logo_y), img_b)

    center_y = logo_y + logo_size//2

    # VS (giữa 2 logo)
    draw.text((W//2, center_y), "VS", fill=(15,23,42), font=font_vs, anchor="mm")

    # Tên đội A — ngay dưới logo
    name_y = logo_y + logo_size + 55
    if match.get("team_a"):
        name_a = match["team_a"][:20]
        draw.text((W//4, name_y), name_a, fill=(15,23,42), font=font_team, anchor="mm")

    # Tên đội B — ngay dưới logo
    if match.get("team_b"):
        name_b = match["team_b"][:20]
        draw.text((W*3//4, name_y), name_b, fill=(15,23,42), font=font_team, anchor="mm")

    # Giờ đấu — màu ĐEN, dưới tên đội
    if match.get("time"):
        time_y = name_y + 90
        draw.text((W//2, time_y), match["time"], fill=(15, 23, 42), font=font_time, anchor="mm")

    # Giải đấu (header) — trắng Bold
    if match.get("league"):
        draw.text((W//2, 60), match["league"].upper(), fill=(255,255,255), font=font_league, anchor="mm")

    # BLV (footer) — trắng Bold, cùng font/màu như header giải đấu
    if match.get("blv"):
        draw.text((W//2, H - 50), f"🎙 BLV: {match['blv']}", fill=(255,255,255), font=font_blv, anchor="mm")

    bg.save(out_path, "PNG", optimize=True)
    return out_path

def parse_time_sort(match_time):
    """
    FIX 2: Chuyển '22:00 25/04' thành số để sort đúng theo thời gian thực tế.
    Sort key: ngày * 10000 + giờ * 100 + phút
    Ví dụ: 23:30 25/04 -> 25*10000 + 23*100 + 30 = 252330
            00:00 26/04 -> 26*10000 + 00*100 + 00 = 260000
    => 260000 > 252330 => 26/04 00:00 xếp SAU 25/04 23:30 ✓
    """
    try:
        parts = match_time.strip().split()
        hm = parts[0].split(":")
        hour = int(hm[0])
        minute = int(hm[1])
        if len(parts) > 1:
            dm = parts[1].split("/")
            day = int(dm[0])
            month = int(dm[1]) if len(dm) > 1 else 1
        else:
            day, month = 25, 4
        # Sort: tháng * 10000000 + ngày * 10000 + giờ * 100 + phút
        return month * 10000000 + day * 10000 + hour * 100 + minute
    except:
        return 999999999

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

        # Lấy cate_id + tên môn từ icon và class
        cate_id = "1"
        cate_name_raw = ""
        cate_match = re.search(r'item_cate_(\d+)', card_class)
        if cate_match:
            cate_id = cate_match.group(1)
        # Lấy tên môn từ alt của icon-cate
        icon_img = card.select_one(f"img[src*='icon-cate-{cate_id}']")
        if icon_img and icon_img.get("alt"):
            cate_name_raw = icon_img.get("alt","")

        SKIP_ALTS = {"","Bóng đá","Bóng rổ","Cầu Lông","Tennis","Billiards",
                     "Võ Thuật","Bóng chuyền","Pickleball","Bóng Rổ"}
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

        # BLV: ưu tiên BLV online (có tên) lên trước
        blv_list = []
        for blv_a in card.select("a[href*='?blv=']"):
            blv_href = blv_a.get("href", "")
            blv_id_m = re.search(r'\?blv=(\d+)', blv_href)
            blv_name = blv_a.get_text(strip=True)
            if blv_id_m and blv_name:
                blv_list.append({"id": blv_id_m.group(1), "name": blv_name})

        # FIX 3: Ẩn trận không có BLV — bỏ qua ngay tại đây
        if not blv_list:
            continue

        blv_names = ", ".join([b["name"] for b in blv_list])
        name = f"{team_a} vs {team_b}" if team_a and team_b else href.split("/")[2][:50]

        matches.append({
            "cate_name_raw": cate_name_raw,
            "url": url,
            "match_id": match_id,
            "name": name,
            "time": match_time,
            "time_sort": parse_time_sort(match_time),
            "team_a": team_a,
            "team_b": team_b,
            "logo_a": logo_a,
            "logo_b": logo_b,
            "league": league,
            "blv": blv_names,
            "is_live": is_live,
            "blv_list": blv_list,
            "cate_id": cate_id,
        })

    # Sắp xếp: LIVE trước, sau đó theo giờ tăng dần
    matches.sort(key=lambda m: (0 if m["is_live"] else 1, m["time_sort"]))
    return matches

def get_streams(match_id, blv_list):
    """
    Lấy stream từ tất cả BLV có tên (bỏ channel_id=0 là sóng quốc tế).
    Ưu tiên: thu thập từng BLV theo thứ tự, Link 1 sẽ là BLV đầu tiên có stream.
    """
    streams = []

    # Loại channel_id=0 (sóng nhà đài/quốc tế không có BLV)
    named_blv = [b for b in blv_list if b["name"].strip() and b["id"] != "0"]
    if not named_blv:
        return []

    for blv in named_blv[:4]:  # Tối đa 4 BLV
        ch_id = blv["id"]
        try:
            url = f"{CBOX_URL}?match_id={match_id}&channel_id={ch_id}"
            res = requests.get(url, headers=HEADERS, timeout=10)
            found = re.findall(r'https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*', res.text)
            for lnk in found:
                clean = lnk.replace("\\u0026", "&").replace("\\/", "/")
                if clean not in streams:
                    streams.append(clean)
                    print(f"    BLV [{blv['name']}] -> {clean[:60]}...")
        except Exception as e:
            print(f"    Loi cbox {match_id}/{ch_id} ({blv['name']}): {e}")
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

    label_text  = "● LIVE" if match["is_live"] else "🕐 Sắp"
    label_color = "#ff4444" if match["is_live"] else "#aaaaaa"

    display_name = match["name"]
    if match["time"]:
        display_name = f"{match['name']} | {match['time']}"

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
            "blv": match.get("blv", ""),
            "is_live": match["is_live"],
            "cate_name": match.get("cate_name_raw", ""),
        }
    }

    if thumb_url:
        channel["image"] = {
            "padding": 1,
            "background_color": "#ffffff",
            "display": "contain",
            "url": thumb_url,
            "width": 1600,
            "height": 1200
        }

    return channel

def main():
    print("Lay danh sach tran tu cakhiatv247...")
    matches = get_matches()

    live_count = sum(1 for m in matches if m["is_live"])
    print(f"Tong: {len(matches)} | LIVE: {live_count} | Sap: {len(matches)-live_count}\n")

    # Nhóm theo môn thể thao
    cate_channels = {}  # cate_id -> list of channels

    for i, match in enumerate(matches):
        cate_id = match["cate_id"]
        status = "LIVE" if match["is_live"] else "SAP"
        print(f"[{status} {i+1}/{len(matches)}] {match['name']} ({match['time']}) | BLV: {match['blv']}")

        streams = []
        if match["is_live"]:
            streams = get_streams(match["match_id"], match["blv_list"])
            print(f"  stream: {len(streams)} link")
            if not streams:
                print(f"  Bo qua - khong co stream")

        uid = make_id(match["url"], "kaytee")
        thumb_path = make_thumbnail(match, uid)
        cache_key = match.get("logo_a","") + match.get("logo_b","") + THUMB_VERSION
        logo_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
        thumb_url = f"{REPO_RAW}/{thumb_path}?v={logo_hash}" if REPO_RAW else ""

        channel = build_channel(match, streams, thumb_url)

        if cate_id not in cate_channels:
            cate_channels[cate_id] = []
        cate_channels[cate_id].append(channel)

        time.sleep(0.2)

    # Build groups theo môn
    groups = []
    for cate_id, channels in cate_channels.items():
        cate_info = CATE_MAP.get(cate_id, "🏅 Thể Thao")
        emoji = cate_info.split(" ")[0]
        raw_name = channels[0].get("org_metadata",{}).get("cate_name","") if channels else ""
        if not raw_name:
            cate_name = cate_info
        else:
            cate_name = f"{emoji} {raw_name}"
        groups.append({
            "id": f"cate_{cate_id}",
            "name": cate_name,
            "display": "vertical",
            "grid_number": 2,
            "enable_detail": False,
            "channels": channels
        })

    # Sắp xếp: Bóng đá (cate 1) lên đầu
    groups.sort(key=lambda g: (0 if g["id"] == "cate_1" else 1, g["name"]))

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

    total = sum(len(g["channels"]) for g in groups)
    print(f"\nXong! {total} kenh, {len(groups)} mon the thao -> output.json")

if __name__ == "__main__":
    main()
