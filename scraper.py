import requests
from bs4 import BeautifulSoup
import json
import hashlib
import re
import time
import os
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# ─────────────────────────────────────────────────────────────────────────────
# TIMEZONE & IS_LIVE — fix theo giờ VN thực
# ─────────────────────────────────────────────────────────────────────────────

VN_TZ       = timezone(timedelta(hours=7))
LIVE_BEFORE = timedelta(minutes=15)
LIVE_AFTER  = timedelta(hours=2, minutes=30)


def now_vn() -> datetime:
    return datetime.now(tz=VN_TZ)


def parse_kickoff(time_str: str):
    """Parse chuỗi giờ site → datetime aware (VN tz). Trả None nếu không parse được."""
    if not time_str or not time_str.strip():
        return None
    s     = time_str.strip()
    today = now_vn()
    year  = today.year

    # groups() trả về tuple 0-indexed
    patterns = [
        # "22:00 25/04/2025" → (hh, mm, dd, mo, yyyy)
        (r"(\d{1,2}):(\d{2})\s+(\d{1,2})/(\d{1,2})/(\d{4})",
         lambda m: datetime(int(m[4]), int(m[3]), int(m[2]), int(m[0]), int(m[1]), tzinfo=VN_TZ)),
        # "22:00 25/04"      → (hh, mm, dd, mo)
        (r"(\d{1,2}):(\d{2})\s+(\d{1,2})/(\d{1,2})$",
         lambda m: datetime(year,    int(m[3]), int(m[2]), int(m[0]), int(m[1]), tzinfo=VN_TZ)),
        # "22:00"            → (hh, mm)
        (r"^(\d{1,2}):(\d{2})$",
         lambda m: datetime(today.year, today.month, today.day, int(m[0]), int(m[1]), tzinfo=VN_TZ)),
    ]
    for pattern, builder in patterns:
        match = re.search(pattern, s)
        if match:
            try:
                return builder(match.groups())
            except ValueError:
                pass
    return None


def calc_is_live(html_flag: bool, time_str: str) -> bool:
    """HTML flag OR cửa sổ [KO-15p, KO+2h30] theo giờ VN."""
    if html_flag:
        return True
    kickoff = parse_kickoff(time_str)
    if kickoff is None:
        return False
    now = now_vn()
    return (kickoff - LIVE_BEFORE) <= now <= (kickoff + LIVE_AFTER)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://cakhiatv247.net/",
}

BASE_URL   = "https://cakhiatv247.net"
CBOX_URL   = "https://cbox-v2.cakhiatv89.com/"
THUMBS_DIR = "thumbs"
REPO_RAW   = os.environ.get("REPO_RAW", "")

CATE_MAP = {
    "1":  "⚽ Bóng Đá",
    "2":  "🥊 Võ Thuật",
    "4":  "🎱 Billiards",
    "13": "🏸 Cầu Lông",
    "20": "🏀 Bóng Rổ",
    "27": "🎾 Tennis",
    "50": "🏐 Bóng Chuyền",
}

EXCLUDE_LEAGUES_AMERICA = [
    "mls", "major league soccer",
    "liga mx", "liga de expansion",
    "brasileirao", "brasileirão", "serie a brasil", "campeonato brasileiro", "brazilian",
    "copa do brasil",
    "argentine", "argentina", "liga profesional", "copa de la liga",
    "colombian", "colombia", "liga betplay", "categoria primera", "primera a",
    "chile", "primera division chile",
    "ecuador", "liga pro ecuador",
    "peru", "liga 1 peru", "liga 1 perú",
    "venezuela", "liga futve",
    "paraguay", "apertura paraguay",
    "uruguay", "primera division uruguay",
    "bolivia", "division profesional",
    "inter miami", "new england", "la galaxy", "nycfc",
    "concacaf", "conmebol",
    "copa america", "copa sudamericana", "copa libertadores",
    "jupiler", "pro league", "first division a", "belgian",
    "efbet league", "parva liga", "bulgarian",
    "super lig", "tff", "turkish", "süper lig",
]

SKIP_ALTS = {
    "", "Bóng đá", "Bóng rổ", "Cầu Lông", "Tennis", "Billiards",
    "Võ Thuật", "Bóng chuyền", "Pickleball", "Bóng Rổ",
}

THUMB_VERSION = "v5"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def is_america_league(league_name: str) -> bool:
    lower = league_name.lower()
    return any(kw in lower for kw in EXCLUDE_LEAGUES_AMERICA)


def make_id(text, prefix):
    h = hashlib.md5(text.encode()).hexdigest()[:10]
    return f"{prefix}-{h}"


def fetch_image(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        return Image.open(BytesIO(res.content)).convert("RGBA")
    except:
        return None


def parse_time_sort(match_time: str) -> int:
    """Dùng parse_kickoff để sort đúng theo thời gian thực."""
    kickoff = parse_kickoff(match_time)
    if kickoff:
        return kickoff.month * 10_000_000 + kickoff.day * 10_000 + kickoff.hour * 100 + kickoff.minute
    return 999_999_999


def is_within_24h(match_time: str, cate_id: str = "1") -> bool:
    """Bóng đá: chỉ hiển thị trận trong 24h tới và tối đa 6h đã qua. Môn khác: True luôn."""
    if cate_id != "1":
        return True
    kickoff = parse_kickoff(match_time)
    if kickoff is None:
        return True
    now   = now_vn()
    lower = now - timedelta(hours=6)
    upper = now + timedelta(hours=24)
    return lower <= kickoff <= upper


# ─────────────────────────────────────────────────────────────────────────────
# THUMBNAIL
# ─────────────────────────────────────────────────────────────────────────────

def make_thumbnail(match, channel_id):
    os.makedirs(THUMBS_DIR, exist_ok=True)
    cache_key = match.get("logo_a", "") + match.get("logo_b", "") + THUMB_VERSION
    logo_hash = hashlib.md5(cache_key.encode()).hexdigest()[:8]
    out_path  = f"{THUMBS_DIR}/{channel_id}_{logo_hash}.png"

    if os.path.exists(out_path):
        return out_path

    W, H = 1600, 1200
    bg   = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(bg)

    draw.rectangle([(0, 0), (W - 1, H - 1)], outline=(220, 220, 220), width=4)

    HEADER_H = 120
    FOOTER_H = 100
    draw.rectangle([(0, 0),          (W, HEADER_H)],      fill=(15, 23, 42))
    draw.rectangle([(0, H - FOOTER_H), (W, H)],           fill=(15, 23, 42))

    FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font_vs     = ImageFont.truetype(FONT_BOLD, 120)
        font_time   = ImageFont.truetype(FONT_BOLD, 85)
        font_team   = ImageFont.truetype(FONT_BOLD, 52)
        font_league = ImageFont.truetype(FONT_BOLD, 50)
        font_blv    = ImageFont.truetype(FONT_BOLD, 50)
    except:
        font_vs = font_time = font_team = font_league = font_blv = ImageFont.load_default()

    content_top = HEADER_H
    content_bot = H - FOOTER_H
    content_h   = content_bot - content_top

    logo_size = 310
    logo_y    = content_top + int(content_h * 0.06)
    name_y    = logo_y + logo_size + 55
    gap_top   = name_y + 60
    time_y    = (gap_top + content_bot) // 2

    for logo_key, x_frac in (("logo_a", 1/4), ("logo_b", 3/4)):
        if match.get(logo_key):
            img = fetch_image(match[logo_key])
            if img:
                img = img.resize((logo_size, logo_size), Image.LANCZOS)
                x   = int(W * x_frac) - logo_size // 2
                bg.paste(img, (x, logo_y), img)

    vs_y = logo_y + logo_size // 2
    draw.text((W // 2, vs_y),      "VS",                      fill=(15, 23, 42),  font=font_vs,     anchor="mm")

    if match.get("team_a"):
        draw.text((W // 4,     name_y), match["team_a"][:20], fill=(15, 23, 42),  font=font_team,   anchor="mm")
    if match.get("team_b"):
        draw.text((W * 3 // 4, name_y), match["team_b"][:20], fill=(15, 23, 42),  font=font_team,   anchor="mm")
    if match.get("time"):
        draw.text((W // 2,     time_y), match["time"],         fill=(200, 20, 20), font=font_time,   anchor="mm")
    if match.get("league"):
        draw.text((W // 2, HEADER_H // 2), match["league"].upper(),
                  fill=(255, 255, 255), font=font_league, anchor="mm")
    if match.get("blv"):
        draw.text((W // 2, H - FOOTER_H // 2), f"BLV: {match['blv']}",
                  fill=(255, 255, 255), font=font_blv, anchor="mm")

    bg.save(out_path, "PNG", optimize=True)
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPE MATCHES
# ─────────────────────────────────────────────────────────────────────────────

def get_matches():
    res  = requests.get(BASE_URL, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(res.text, "html.parser")

    matches = []
    seen    = set()

    for card in soup.select("div.grid-matches__item"):
        a_tag = card.select_one("a[href*='/truc-tiep/']")
        if not a_tag:
            continue
        href = a_tag.get("href", "")
        if not href or href in seen:
            continue
        seen.add(href)

        url      = BASE_URL + href if href.startswith("/") else href
        match_id = re.search(r'/(\d+)(?:\?|$)', href)
        if not match_id:
            continue
        match_id = match_id.group(1)

        card_class = " ".join(card.get("class", []))

        # ── Cate ──────────────────────────────────────────────────────────────
        cate_id       = "1"
        cate_name_raw = ""
        cate_m        = re.search(r'item_cate_(\d+)', card_class)
        if cate_m:
            cate_id = cate_m.group(1)
        icon_img = card.select_one(f"img[src*='icon-cate-{cate_id}']")
        if icon_img:
            cate_name_raw = icon_img.get("alt", "")

        # ── Teams / Logos ──────────────────────────────────────────────────────
        team_imgs = [
            i for i in card.select("img[width='64']")
            if i.get("alt", "").strip() and i.get("alt", "") not in SKIP_ALTS
        ]
        logo_a = logo_b = team_a = team_b = ""
        if len(team_imgs) >= 1:
            logo_a = team_imgs[0].get("data-src") or team_imgs[0].get("src", "")
            team_a = team_imgs[0].get("alt", "")
        if len(team_imgs) >= 2:
            logo_b = team_imgs[1].get("data-src") or team_imgs[1].get("src", "")
            team_b = team_imgs[1].get("alt", "")

        # ── League ────────────────────────────────────────────────────────────
        league_tag = card.select_one("span.s_by_name")
        league     = league_tag.get_text(strip=True) if league_tag else ""

        # Bỏ giải châu Mỹ (chỉ bóng đá)
        if cate_id == "1" and is_america_league(league):
            continue

        # ── Giờ ───────────────────────────────────────────────────────────────
        time_tag   = card.select_one("span.font-mono")
        match_time = time_tag.get_text(strip=True) if time_tag else ""

        # Lọc 24h tới (chỉ bóng đá)
        if not is_within_24h(match_time, cate_id):
            continue

        # ── BLV — chỉ lấy từ section "BLV ONLINE" ────────────────────────────
        blv_list            = []
        blv_online_section  = None
        for el in card.find_all(string=re.compile(r'BLV\s+ONLINE', re.I)):
            blv_online_section = el.parent
            break

        if blv_online_section:
            scope = blv_online_section.parent or blv_online_section
            for blv_a in scope.find_all("a", href=re.compile(r'\?blv=')):
                blv_id_m = re.search(r'\?blv=(\d+)', blv_a.get("href", ""))
                blv_name = blv_a.get_text(strip=True)
                if blv_id_m and blv_name and blv_id_m.group(1) != "0":
                    blv_list.append({"id": blv_id_m.group(1), "name": blv_name})

        # Ẩn trận không có BLV online — không fallback
        if not blv_list:
            continue

        blv_names = ", ".join(b["name"] for b in blv_list)
        name      = f"{team_a} vs {team_b}" if team_a and team_b else href.split("/")[2][:50]

        # ── is_live: HTML flag + cửa sổ giờ VN ───────────────────────────────
        html_live_flag = "stream_m_live" in card_class
        is_live_flag   = calc_is_live(html_live_flag, match_time)

        matches.append({
            "cate_name_raw": cate_name_raw,
            "url":        url,
            "match_id":   match_id,
            "name":       name,
            "time":       match_time,
            "time_sort":  parse_time_sort(match_time),
            "team_a":     team_a,
            "team_b":     team_b,
            "logo_a":     logo_a,
            "logo_b":     logo_b,
            "league":     league,
            "blv":        blv_names,
            "is_live":    is_live_flag,
            "blv_list":   blv_list,
            "cate_id":    cate_id,
        })

    # LIVE lên đầu → sort theo giờ tăng dần
    matches.sort(key=lambda m: (0 if m["is_live"] else 1, m["time_sort"]))
    return matches


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPE STREAMS
# ─────────────────────────────────────────────────────────────────────────────

def get_streams(match_id, blv_list):
    """
    Lấy stream từ tất cả BLV có tên (bỏ channel_id=0 là sóng quốc tế).
    Ưu tiên: thu thập từng BLV theo thứ tự, Link 1 sẽ là BLV đầu tiên có stream.
    """
    named_blv = [b for b in blv_list if b["name"].strip() and b["id"] != "0"]
    if not named_blv:
        return []

    streams = []
    for blv in named_blv[:4]:
        ch_id = blv["id"]
        try:
            url = f"{CBOX_URL}?match_id={match_id}&channel_id={ch_id}"
            res = requests.get(url, headers=HEADERS, timeout=10)
            found = re.findall(r'https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*', res.text)
            added = 0
            for lnk in found:
                clean = lnk.replace("\\u0026", "&").replace("\\/", "/")
                if clean not in streams:
                    streams.append(clean)
                    added += 1
            print(f"    BLV [{blv['name']}] ch={ch_id} -> {added} link(s)")
        except Exception as e:
            print(f"    Loi cbox {match_id}/{ch_id} ({blv['name']}): {e}")
        time.sleep(0.2)

    return streams


# ─────────────────────────────────────────────────────────────────────────────
# BUILD CHANNEL JSON
# ─────────────────────────────────────────────────────────────────────────────

def label_stream(url: str) -> str | None:
    """
    Đặt tên link theo domain. Trả về None = ẩn link đó.
    """
    if "cdn-hls.cakhiatv89.com" in url:
        return "Link HD"
    if "live.alilicloud.com" in url:
        return "Link nhà đài"
    if "bclive.zlylive.com" in url:
        return None   # ẩn
    return None       # domain lạ khác → ẩn luôn cho an toàn


def build_channel(match, streams, thumb_url=""):
    uid    = make_id(match["url"], "kaytee")
    src_id = make_id(match["url"], "src")
    ct_id  = make_id(match["url"], "ct")
    st_id  = make_id(match["url"], "st")

    stream_links = []
    for i, s_url in enumerate(streams):
        name = label_stream(s_url)
        if name is None:
            continue   # ẩn link này
        lnk_id = make_id(s_url + str(i), "lnk")
        stream_links.append({
            "id":      lnk_id,
            "name":    name,
            "type":    "hls",
            "default": len(stream_links) == 0,  # link đầu tiên còn lại là default
            "url":     s_url,
            "request_headers": [
                {"key": "Referer",    "value": "https://cakhiatv247.net/"},
                {"key": "User-Agent", "value": "Mozilla/5.0"},
            ],
        })

    label_text  = "● LIVE" if match["is_live"] else "🕐 Sắp"
    label_color = "#ff4444" if match["is_live"] else "#aaaaaa"

    display_name = match["name"]
    if match["time"]:
        display_name = f"{match['name']} | {match['time']}"

    channel = {
        "id":            uid,
        "name":          display_name,
        "type":          "single",
        "display":       "thumbnail-only",
        "enable_detail": False,
        "labels": [{"text": label_text, "position": "top-left",
                    "color": "#00000080", "text_color": label_color}],
        "sources": [{
            "id":   src_id,
            "name": "CakhiaTV",
            "contents": [{
                "id":   ct_id,
                "name": match["name"],
                "streams": [{"id": st_id, "name": "KT", "stream_links": stream_links}],
            }],
        }],
        "org_metadata": {
            "league":    match.get("league",        ""),
            "team_a":    match.get("team_a",        ""),
            "team_b":    match.get("team_b",        ""),
            "logo_a":    match.get("logo_a",        ""),
            "logo_b":    match.get("logo_b",        ""),
            "time":      match.get("time",          ""),
            "blv":       match.get("blv",           ""),
            "is_live":   match["is_live"],
            "cate_name": match.get("cate_name_raw", ""),
        },
    }

    if thumb_url:
        channel["image"] = {
            "padding":          1,
            "background_color": "#ffffff",
            "display":          "contain",
            "url":              thumb_url,
            "width":            1600,
            "height":           1200,
        }

    return channel


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(THUMBS_DIR, exist_ok=True)
    print(f"Gio VN hien tai : {now_vn().strftime('%H:%M %d/%m/%Y')}")
    print("Lay danh sach tran tu cakhiatv247...")
    matches = get_matches()

    live_count = sum(1 for m in matches if m["is_live"])
    print(f"Tong: {len(matches)} | LIVE: {live_count} | Sap: {len(matches)-live_count}\n")

    # Khởi tạo sẵn tất cả môn để cố định thứ tự group
    cate_channels = {cate_id: [] for cate_id in CATE_MAP}

    for i, match in enumerate(matches):
        cate_id = match["cate_id"]
        status  = "LIVE" if match["is_live"] else "SAP"
        print(f"[{status} {i+1}/{len(matches)}] {match['name']} ({match['time']}) | BLV: {match['blv']}")

        streams = []
        if match["is_live"]:
            streams = get_streams(match["match_id"], match["blv_list"])

            # Bóng đá & Bóng rổ: swap link[0] ↔ link[1]
            # (link[0] từ cbox thường là sóng đài, link[1] mới là BLV VN)
            if cate_id in ("1", "20") and len(streams) >= 2:
                streams = [streams[1], streams[0]] + streams[2:]
                label = "football" if cate_id == "1" else "basketball"
                print(f"  [{label}] swapped link 1<->2")

            print(f"  stream: {len(streams)} link")
            if not streams:
                print(f"  Bo qua - khong co stream")

        uid       = make_id(match["url"], "kaytee")
        thumb_path = make_thumbnail(match, uid)
        cache_key  = match.get("logo_a", "") + match.get("logo_b", "") + THUMB_VERSION
        logo_hash  = hashlib.md5(cache_key.encode()).hexdigest()[:8]
        thumb_url  = f"{REPO_RAW}/{thumb_path}?v={logo_hash}" if REPO_RAW else ""

        channel = build_channel(match, streams, thumb_url)

        if cate_id not in cate_channels:
            cate_channels[cate_id] = []
        cate_channels[cate_id].append(channel)

        time.sleep(0.2)

    # Build groups
    groups = []
    for cate_id, channels in cate_channels.items():
        if not channels:
            continue  # bỏ môn không có trận
        cate_info  = CATE_MAP.get(cate_id, "🏅 Thể Thao")
        emoji      = cate_info.split(" ")[0]
        raw_name   = channels[0].get("org_metadata", {}).get("cate_name", "") if channels else ""
        base_name  = f"{emoji} {raw_name}" if raw_name else cate_info

        # Số trận LIVE trong group
        live_count = sum(1 for ch in channels if ch.get("org_metadata", {}).get("is_live", False))
        cate_name  = f"{base_name} ({live_count} LIVE)" if live_count > 0 else base_name

        groups.append({
            "id":            f"cate_{cate_id}",
            "name":          cate_name,
            "display":       "vertical",
            "grid_number":   2,
            "enable_detail": False,
            "channels":      channels,
        })

    # Bóng đá lên đầu
    groups.sort(key=lambda g: (0 if g["id"] == "cate_1" else 1, g["name"]))

    output = {
        "id":          "cakhia",
        "url":         "https://cakhiatv247.net",
        "name":        "CakhiaTV",
        "color":       "#1cb57a",
        "grid_number": 3,
        "image":       {"type": "cover", "url": "https://cakhiatv247.net/img/logo-247-1.png"},
        "groups":      groups,
    }

    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(len(g["channels"]) for g in groups)
    print(f"\nXong! {total} kenh, {len(groups)} mon the thao -> output.json")


if __name__ == "__main__":
    main()
