import requests
from bs4 import BeautifulSoup
import json
import hashlib
import re
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://cakhiatv247.net/"
}

BASE_URL = "https://cakhiatv247.net"
CBOX_URL = "https://cbox-v2.cakhiatv89.com/"

def make_id(text, prefix):
    h = hashlib.md5(text.encode()).hexdigest()[:10]
    return f"{prefix}-{h}"

def get_matches():
    """Lấy danh sách trận từ trang chủ, kèm logo và trạng thái"""
    res = requests.get(BASE_URL, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(res.text, "html.parser")

    seen = set()
    matches = []

    for a in soup.select("a[href*='/truc-tiep/']"):
        href = a.get("href", "")
        if not href or href in seen:
            continue
        seen.add(href)

        url = BASE_URL + href if href.startswith("/") else href

        # Lấy match_id từ URL (số cuối)
        match_id = re.search(r'/(\d+)$', href)
        if not match_id:
            continue
        match_id = match_id.group(1)

        # ── Logo + tên đội ──
        # Mỗi đội nằm trong div chứa img cdn.rapid-api.icu
        team_imgs = a.select("img[src*='cdn.rapid-api.icu']")
        
        logo_a, logo_b = "", ""
        team_a, team_b = "", ""

        if len(team_imgs) >= 1:
            logo_a = team_imgs[0].get("src", "")
            team_a = team_imgs[0].get("alt", "")
        if len(team_imgs) >= 2:
            logo_b = team_imgs[1].get("src", "")
            team_b = team_imgs[1].get("alt", "")

        # ── Trạng thái LIVE ──
        # Trận LIVE: div logo có class ring-red-500
        # Trận chưa live: div logo có class ring-blue-500
        is_live = False
        logo_divs = a.select("div[class*='ring-red']")
        if logo_divs:
            is_live = True

        # Cũng kiểm tra thêm text "LIVE" hoặc span có màu đỏ
        live_spans = a.select("span[class*='red'], span[class*='live']")
        if live_spans:
            is_live = True

        # ── Giờ đấu ──
        time_tag = a.find(string=re.compile(r'\d{2}:\d{2}'))
        match_time = time_tag.strip() if time_tag else ""

        # ── Tên trận ──
        if team_a and team_b:
            name = f"{team_a} vs {team_b}"
        else:
            # Fallback: lấy từ href
            slug = href.split("/")[2] if len(href.split("/")) > 2 else ""
            name = slug.replace("-", " ").title()[:60]

        # ── Giải đấu ──
        league_tag = a.find(class_=re.compile(r'text-link-stream'))
        league = ""
        if league_tag:
            text = league_tag.get_text(strip=True)
            # Format: "Bóng đá, 23:30" hoặc "K-League, 23:30"
            parts = text.split(",")
            if parts:
                league = parts[0].strip()

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
        })

    return matches

def get_streams(match_id):
    """Gọi cbox API để lấy link m3u8, thử các channel_id phổ biến"""
    streams = []

    # Thử channel_id = 0 (mặc định) trước, rồi các ID phổ biến
    channel_ids = ["0", "145238", "145274", "145476"]

    for ch_id in channel_ids:
        try:
            url = f"{CBOX_URL}?match_id={match_id}&channel_id={ch_id}"
            res = requests.get(url, headers=HEADERS, timeout=10)

            # Decode unicode escape (\u0026 → &)
            text = res.text

            # Tìm link m3u8 từ cdn-hls.cakhiatv89.com
            cakhia_links = re.findall(
                r'https://cdn-hls\.cakhiatv89\.com/live/[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*',
                text
            )
            # Tìm link alilicloud
            alili_links = re.findall(
                r'https://live\.alilicloud\.com/live/[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*',
                text
            )

            # Xử lý unicode escape trong link
            all_raw = cakhia_links + alili_links
            for lnk in all_raw:
                clean = lnk.replace("\\u0026", "&").replace("\\/", "/")
                if clean not in streams:
                    streams.append(clean)

            if streams:
                break  # Có link rồi, không cần thử thêm

        except Exception as e:
            print(f"    ⚠️ Lỗi cbox {match_id}/{ch_id}: {e}")
        time.sleep(0.2)

    return streams

def build_channel(match, streams):
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

    # Label: LIVE đỏ hoặc giờ đấu
    label_text = "● LIVE" if match["is_live"] else f"🕐 {match['time']}"
    label_color = "#ff0000" if match["is_live"] else "#ffffff"

    return {
        "id": uid,
        "name": match["name"],
        "type": "single",
        "display": "thumbnail-only",
        "enable_detail": False,
        "labels": [
            {
                "text": label_text,
                "position": "top-left",
                "color": "#00000080",
                "text_color": label_color
            }
        ],
        "sources": [{
            "id": src_id,
            "name": "CakhiaTV",
            "contents": [{
                "id": ct_id,
                "name": match["name"],
                "streams": [{
                    "id": st_id,
                    "name": "KT",
                    "stream_links": stream_links
                }]
            }]
        }],
        "org_metadata": {
            "league": match.get("league", ""),
            "team_a": match.get("team_a", ""),
            "team_b": match.get("team_b", ""),
            "logo": match.get("logo_a", ""),      # logo chính (đội nhà)
            "logo_a": match.get("logo_a", ""),
            "logo_b": match.get("logo_b", ""),
            "is_live": match["is_live"],
        }
    }

def main():
    print("🔍 Lấy danh sách trận từ cakhiatv247...")
    matches = get_matches()
    print(f"✅ Tìm thấy {len(matches)} trận\n")

    live_count = sum(1 for m in matches if m["is_live"])
    print(f"   🔴 Đang LIVE: {live_count}")
    print(f"   🕐 Sắp diễn ra: {len(matches) - live_count}\n")

    # Tách 2 nhóm
    live_matches    = [m for m in matches if m["is_live"]]
    upcoming_matches = [m for m in matches if not m["is_live"]]

    live_channels     = []
    upcoming_channels = []

    all_matches = live_matches + upcoming_matches

    for i, match in enumerate(all_matches):
        status = "🔴 LIVE" if match["is_live"] else "🕐 Sắp"
        print(f"[{i+1}/{len(all_matches)}] {status} {match['name']}")

        # Chỉ lấy stream cho trận LIVE
        streams = []
        if match["is_live"]:
            streams = get_streams(match["match_id"])
            print(f"    → {len(streams)} link stream")
            if not streams:
                print(f"    ⚠️ Không có stream, bỏ qua")
                continue
        
        channel = build_channel(match, streams)

        if match["is_live"]:
            live_channels.append(channel)
        else:
            upcoming_channels.append(channel)

        time.sleep(0.2)

    # Build output JSON với 2 group
    groups = []

    if live_channels:
        groups.append({
            "id": "live",
            "name": "🔴 Đang Live",
            "display": "vertical",
            "grid_number": 2,
            "enable_detail": False,
            "channels": live_channels
        })

    if upcoming_channels:
        groups.append({
            "id": "upcoming",
            "name": "🕐 Sắp Diễn Ra",
            "display": "vertical",
            "grid_number": 2,
            "enable_detail": False,
            "channels": upcoming_channels
        })

    output = {
        "id": "cakhia",
        "url": "https://cakhiatv247.net",
        "name": "CakhiaTV",
        "color": "#1cb57a",
        "grid_number": 3,
        "image": {
            "type": "cover",
            "url": "https://cakhiatv247.net/img/logo-247-1.png"
        },
        "groups": groups
    }

    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Xong!")
    print(f"   🔴 Live: {len(live_channels)} kênh")
    print(f"   🕐 Sắp: {len(upcoming_channels)} kênh")
    print(f"   → output.json")

if __name__ == "__main__":
    main()
