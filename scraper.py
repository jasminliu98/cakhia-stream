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
# TIMEZONE & IS_LIVE (FIX CHÍNH)
# ─────────────────────────────────────────────────────────────────────────────

VN_TZ = timezone(timedelta(hours=7))           # UTC+7, không cần pytz

# Cửa sổ coi là "đang live":
#   từ  KO - 15 phút  (vào sớm xem warm-up)
#   đến KO + 2h30     (trận kéo dài + injury time + hiệp phụ)
LIVE_BEFORE = timedelta(minutes=15)
LIVE_AFTER  = timedelta(hours=2, minutes=30)


def now_vn() -> datetime:
    """Thời điểm hiện tại đúng giờ Việt Nam (aware datetime)."""
    return datetime.now(tz=VN_TZ)


def parse_kickoff(time_str: str) -> datetime | None:
    """
    Parse chuỗi giờ thi đấu lấy từ site → datetime aware (VN timezone).

    Các định dạng thực tế trên cakhiatv247.net:
        "22:00 25/04"       ← phổ biến nhất (không có năm)
        "22:00 25/04/2025"
        "22:00"             ← không có ngày → dùng ngày hôm nay
        ""                  → None
    """
    if not time_str or not time_str.strip():
        return None

    s = time_str.strip()
    today = now_vn()
    year  = today.year

    patterns = [
        # "22:00 25/04/2025"  → groups: (hh, mm, dd, mo, yyyy)  index 0-4
        (r"(\d{1,2}):(\d{2})\s+(\d{1,2})/(\d{1,2})/(\d{4})",
         lambda m: datetime(int(m[4]), int(m[3]), int(m[2]),
                            int(m[0]), int(m[1]), tzinfo=VN_TZ)),
        # "22:00 25/04"       → groups: (hh, mm, dd, mo)         index 0-3
        (r"(\d{1,2}):(\d{2})\s+(\d{1,2})/(\d{1,2})$",
         lambda m: datetime(year, int(m[3]), int(m[2]),
                            int(m[0]), int(m[1]), tzinfo=VN_TZ)),
        # "22:00"             → groups: (hh, mm)                  index 0-1
        (r"^(\d{1,2}):(\d{2})$",
         lambda m: datetime(today.year, today.month, today.day,
                            int(m[0]), int(m[1]), tzinfo=VN_TZ)),
    ]

    for pattern, builder in patterns:
        match = re.search(pattern, s)
        if match:
            try:
                return builder(match.groups())
            except ValueError:
                pass

    return None


def calc_is_live(card_is_live_flag: bool, time_str: str) -> bool:
    """
    Tính toán is_live chính xác theo giờ VN.

    Ưu tiên:
    1. Nếu HTML đã có class `stream_m_live`  → True ngay
    2. Nếu có giờ KO parse được              → so sánh với now_vn()
    3. Fallback                               → False
    """
    if card_is_live_flag:
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
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://cakhiatv247.net/",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

BASE_URL  = "https://cakhiatv247.net"
CBOX_URL  = "https://cbox-v2.cakhiatv89.com/"
THUMBS_DIR = "thumbs"
REPO_RAW  = os.environ.get("REPO_RAW", "")

CATE_MAP = {
    "1":  "⚽ Bóng Đá",
    "2":  "🥊 Võ Thuật",
    "13": "🏸 Cầu Lông",
    "20": "🏀 Bóng Rổ",
    "27": "🎾 Tennis",
}

SKIP_ALTS = {
    "", "Bóng đá", "Bóng rổ", "Cầu Lông", "Tennis", "Billiards",
    "Võ Thuật", "Bóng chuyền", "Pickleball", "Bóng Rổ",
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def make_id(text: str, prefix: str) -> str:
    h = hashlib.md5(text.encode()).hexdigest()[:10]
    return f"{prefix}-{h}"


def fetch_image(url: str) -> Image.Image | None:
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        return Image.open(BytesIO(res.content)).convert("RGBA")
    except Exception:
        return None


def parse_time_sort(match_time: str) -> int:
    """
    Chuyển '22:00 25/04' thành số nguyên để sort.
    Trả về (tháng * 1e6 + ngày * 1e4 + giờ * 60 + phút).
    """
    kickoff = parse_kickoff(match_time)
    if kickoff:
        return kickoff.month * 1_000_000 + kickoff.day * 10_000 + kickoff.hour * 60 + kickoff.minute
    # Nếu không parse được (đang live / thiếu dữ liệu) → lên đầu
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# THUMBNAIL
# ─────────────────────────────────────────────────────────────────────────────

def make_thumbnail(match: dict, channel_id: str) -> str:
    os.makedirs(THUMBS_DIR, exist_ok=True)
    logo_hash = hashlib.md5(
        (match.get("logo_a", "") + match.get("logo_b", "")).encode()
    ).hexdigest()[:8]
    out_path = f"{THUMBS_DIR}/{channel_id}_{logo_hash}.png"

    W, H = 1600, 1200
    bg   = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(bg)

    draw.rectangle([(0, 0), (W - 1, H - 1)], outline=(220, 220, 220), width=4)
    draw.rectangle([(0, 0), (W, 120)],        fill=(15, 23, 42))
    draw.rectangle([(0, H - 100), (W, H)],    fill=(15, 23, 42))

    try:
        font_vs     = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 130)
        font_time   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 90)
        font_team   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 55)
        font_league = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        font_blv    = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",      48)
    except Exception:
        font_vs = font_time = font_team = font_league = font_blv = ImageFont.load_default()

    logo_size = 380
    logo_y    = 200

    for logo_key, x_frac in (("logo_a", 1 / 4), ("logo_b", 3 / 4)):
        if match.get(logo_key):
            img = fetch_image(match[logo_key])
            if img:
                img = img.resize((logo_size, logo_size), Image.LANCZOS)
                x   = int(W * x_frac) - logo_size // 2
                bg.paste(img, (x, logo_y), img)

    center_y = logo_y + logo_size // 2
    draw.text((W // 2, center_y - 50),  "VS",              fill=(15, 23, 42),   font=font_vs,     anchor="mm")

    if match.get("time"):
        draw.text((W // 2, center_y + 100), match["time"],  fill=(234, 88, 12),  font=font_time,   anchor="mm")

    if match.get("team_a"):
        draw.text((W // 4, logo_y + logo_size + 60), match["team_a"][:20],
                  fill=(15, 23, 42), font=font_team, anchor="mm")
    if match.get("team_b"):
        draw.text((W * 3 // 4, logo_y + logo_size + 60), match["team_b"][:20],
                  fill=(15, 23, 42), font=font_team, anchor="mm")
    if match.get("league"):
        draw.text((W // 2, 60), match["league"].upper(),
                  fill=(255, 255, 255), font=font_league, anchor="mm")
    if match.get("blv"):
        draw.text((W // 2, H - 50), f"🎙 BLV: {match['blv']}",
                  fill=(134, 239, 172), font=font_blv, anchor="mm")

    bg.save(out_path, "PNG", optimize=True)
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPE MATCHES
# ─────────────────────────────────────────────────────────────────────────────

def get_matches() -> list[dict]:
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

        url = BASE_URL + href if href.startswith("/") else href

        match_id_m = re.search(r"/(\d+)(?:\?|$)", href)
        if not match_id_m:
            continue
        match_id = match_id_m.group(1)

        card_class = " ".join(card.get("class", []))

        # ── Cate ──────────────────────────────────────────────────────────────
        cate_id = "1"
        cate_m  = re.search(r"item_cate_(\d+)", card_class)
        if cate_m:
            cate_id = cate_m.group(1)

        cate_name_raw = ""
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

        # ── Giờ thi đấu ───────────────────────────────────────────────────────
        time_tag   = card.select_one("span.font-mono")
        match_time = time_tag.get_text(strip=True) if time_tag else ""

        # ── BLV ───────────────────────────────────────────────────────────────
        blv_list = []
        for blv_a in card.select("a[href*='?blv=']"):
            blv_id_m = re.search(r"\?blv=(\d+)", blv_a.get("href", ""))
            blv_name = blv_a.get_text(strip=True)
            if blv_id_m and blv_name:
                blv_list.append({"id": blv_id_m.group(1), "name": blv_name})

        blv_names = ", ".join(b["name"] for b in blv_list)
        name      = f"{team_a} vs {team_b}" if team_a and team_b else href.split("/")[2][:50]

        # ── is_live FIX ───────────────────────────────────────────────────────
        # Code gốc chỉ dùng class HTML → sai khi class chưa update hoặc
        # trận sắp diễn ra trong vài phút mà site chưa đánh dấu live.
        # Giờ kết hợp: flag HTML  OR  cửa sổ thời gian theo giờ VN thực.
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

    # LIVE lên đầu, sau đó sort theo giờ tăng dần
    matches.sort(key=lambda m: (0 if m["is_live"] else 1, m["time_sort"]))
    return matches


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPE STREAMS
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_m3u8(match_id: str, channel_id: str) -> list[str]:
    """Gọi cbox lấy m3u8 cho 1 channel_id cụ thể."""
    try:
        url = f"{CBOX_URL}?match_id={match_id}&channel_id={channel_id}"
        res = requests.get(url, headers=HEADERS, timeout=10)
        links = []
        for raw in re.findall(r'https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*', res.text):
            clean = raw.replace("\\u0026", "&").replace("\\/", "/")
            if clean not in links:
                links.append(clean)
        return links
    except Exception as e:
        print(f"    Lỗi cbox {match_id}/{channel_id}: {e}")
        return []


def get_streams(match_id: str, blv_list: list[dict], cate_id: str = "1") -> list[str]:
    """
    Lấy stream links theo đúng logic gốc:

    Bóng đá (cate_id == "1"):
      - Link 0  = channel_id=0  (sóng quốc tế / không BLV)  → đặt đầu tiên
      - Link 1+ = các BLV có tên (theo thứ tự blv_list)

    Môn khác (bóng rổ, võ thuật, ...):
      - Chỉ lấy BLV có tên, bỏ channel_id=0
      - Không có BLV tên → trả về []
    """
    streams: list[str] = []
    named_blv = [b for b in blv_list if b["name"].strip()]

    if cate_id == "1":
        # ── Bóng đá: channel_id=0 lên đầu ──────────────────────────────────
        for lnk in _fetch_m3u8(match_id, "0"):
            if lnk not in streams:
                streams.append(lnk)
        time.sleep(0.2)

        # Sau đó thêm BLV có tên (tối đa 3)
        for blv in named_blv[:3]:
            for lnk in _fetch_m3u8(match_id, blv["id"]):
                if lnk not in streams:
                    streams.append(lnk)
            time.sleep(0.2)

    else:
        # ── Môn khác: chỉ BLV có tên ────────────────────────────────────────
        if not named_blv:
            return []
        for blv in named_blv[:3]:
            links = _fetch_m3u8(match_id, blv["id"])
            for lnk in links:
                if lnk not in streams:
                    streams.append(lnk)
            if streams:
                break          # lấy được rồi thì dừng
            time.sleep(0.2)

    return streams


# ─────────────────────────────────────────────────────────────────────────────
# BUILD CHANNEL JSON
# ─────────────────────────────────────────────────────────────────────────────

def build_channel(match: dict, streams: list[str], thumb_url: str = "") -> dict:
    uid    = make_id(match["url"], "kaytee")
    src_id = make_id(match["url"], "src")
    ct_id  = make_id(match["url"], "ct")
    st_id  = make_id(match["url"], "st")

    stream_links = []
    for i, s_url in enumerate(streams):
        lnk_id = make_id(s_url + str(i), "lnk")
        stream_links.append({
            "id":      lnk_id,
            "name":    f"Link {i + 1}",
            "type":    "hls",
            "default": i == 0,
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

    channel: dict = {
        "id":             uid,
        "name":           display_name,
        "type":           "single",
        "display":        "thumbnail-only",
        "enable_detail":  False,
        "labels": [{
            "text":       label_text,
            "position":   "top-left",
            "color":      "#00000080",
            "text_color": label_color,
        }],
        "sources": [{
            "id":   src_id,
            "name": "CakhiaTV",
            "contents": [{
                "id":   ct_id,
                "name": match["name"],
                "streams": [{
                    "id":           st_id,
                    "name":         "KT",
                    "stream_links": stream_links,
                }],
            }],
        }],
        "org_metadata": {
            "league":     match.get("league",        ""),
            "team_a":     match.get("team_a",        ""),
            "team_b":     match.get("team_b",        ""),
            "logo_a":     match.get("logo_a",        ""),
            "logo_b":     match.get("logo_b",        ""),
            "time":       match.get("time",          ""),
            "blv":        match.get("blv",           ""),
            "is_live":    match["is_live"],
            "cate_name":  match.get("cate_name_raw", ""),
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

def main() -> None:
    print(f"Giờ VN hiện tại : {now_vn().strftime('%H:%M %d/%m/%Y')}")
    print("Lấy danh sách trận từ cakhiatv247...\n")

    matches    = get_matches()
    live_count = sum(1 for m in matches if m["is_live"])
    print(f"Tổng: {len(matches)} | LIVE: {live_count} | Sắp: {len(matches) - live_count}\n")

    cate_channels: dict[str, list[dict]] = {}

    for i, match in enumerate(matches):
        status = "LIVE" if match["is_live"] else "SẮP"
        print(f"[{status} {i + 1}/{len(matches)}] {match['name']} ({match['time']})")

        streams: list[str] = []
        if match["is_live"]:
            streams = get_streams(match["match_id"], match["blv_list"], match["cate_id"])
            print(f"  stream: {len(streams)} link{'(s)' if streams else ' — bỏ qua'}")

        uid        = make_id(match["url"], "kaytee")
        thumb_path = make_thumbnail(match, uid)
        logo_hash  = hashlib.md5(
            (match.get("logo_a", "") + match.get("logo_b", "")).encode()
        ).hexdigest()[:8]
        thumb_url  = f"{REPO_RAW}/{thumb_path}?v={logo_hash}" if REPO_RAW else ""

        channel    = build_channel(match, streams, thumb_url)
        cate_id    = match["cate_id"]

        cate_channels.setdefault(cate_id, []).append(channel)
        time.sleep(0.2)

    # Build groups
    groups = []
    for cate_id, channels in cate_channels.items():
        cate_info = CATE_MAP.get(cate_id, "🏅")
        emoji     = cate_info.split(" ")[0]
        raw_name  = channels[0].get("org_metadata", {}).get("cate_name", "") if channels else ""
        base_name = f"{emoji} {raw_name}" if raw_name else cate_info

        # Đếm số trận đang LIVE trong group này
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
        "image": {
            "type": "cover",
            "url":  "https://cakhiatv247.net/img/logo-247-1.png",
        },
        "groups": groups,
    }

    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total = sum(len(g["channels"]) for g in groups)
    print(f"\nXong! {total} kênh, {len(groups)} môn thể thao → output.json")


if __name__ == "__main__":
    main()
