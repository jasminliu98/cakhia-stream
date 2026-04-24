import requests
from bs4 import BeautifulSoup
import json
import hashlib
import time
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://cakhiatv247.net/"
}

BASE_URL = "https://cakhiatv247.net"

CDN_LINKS = [
    "https://cdn-tvc2.taoxanh.biz/live-phogatv/video/adaptive/2026/03/playlist.m3u8",
    "https://cdn-tvc2.taoxanh.biz/live-phogatv/video/adaptive/2026/04/playlist.m3u8",
]

def make_id(text, prefix):
    h = hashlib.md5(text.encode()).hexdigest()[:10]
    return f"{prefix}-{h}"

def get_matches():
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

        # Lấy tên 2 đội
        teams = a.select("img[alt]")
        team_names = [t.get("alt", "") for t in teams if t.get("alt") and t.get("alt") != "Bóng đá"]

        # Lấy logo
        logos = []
        for img in a.select("img[src]"):
            src = img.get("src", "")
            if "soccer.svg" not in src and "icon" not in src:
                logos.append(src)

        # Lấy giờ đấu
        text = a.get_text(" ", strip=True)
        time_match = re.search(r'\d{2}:\d{2}', text)
        match_time = time_match.group(0) if time_match else ""

        # Tên trận
        if len(team_names) >= 2:
            name = f"{team_names[0]} vs {team_names[1]}"
        else:
            name = text[:60]

        if name:
            matches.append({
                "url": url,
                "name": name,
                "time": match_time,
                "logo_a": logos[0] if len(logos) > 0 else "",
                "logo_b": logos[1] if len(logos) > 1 else "",
            })

    return matches

def get_match_detail(match_url):
    """Lấy thêm thông tin từ trang trận đấu: giải đấu, logo rõ hơn"""
    try:
        res = requests.get(match_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")

        # Lấy tên giải từ title
        title = soup.find("title")
        league = ""
        if title:
            t = title.get_text()
            # Ví dụ: "Xem trực tiếp Real Betis vs Real Madrid ... Spanish La Liga"
            parts = t.split(" ")
            if len(parts) > 5:
                league = " ".join(parts[-3:]).strip()

        # Lấy logo đội từ thẻ img có src cdn.rapid-api hoặc cdn-live.taoxanh
        logos = []
        for img in soup.select("img[src*='cdn']"):
            src = img.get("src", "")
            if any(x in src for x in ["rapid-api", "taoxanh.biz/live-phogatv/football"]):
                logos.append(src)

        # Lấy thumbnail
        thumb = ""
        og_img = soup.find("meta", property="og:image")
        if og_img:
            thumb = og_img.get("content", "")

        return {
            "league": league,
            "logo_a": logos[0] if len(logos) > 0 else "",
            "logo_b": logos[1] if len(logos) > 1 else "",
            "thumb": thumb,
        }
    except:
        return {"league": "", "logo_a": "", "logo_b": "", "thumb": ""}

def build_channel(match, detail):
    uid = make_id(match["url"], "kaytee")
    src_id = make_id(match["url"], "src")
    ct_id  = make_id(match["url"], "ct")
    st_id  = make_id(match["url"], "st")

    stream_links = []
    for i, cdn_url in enumerate(CDN_LINKS):
        lnk_id = make_id(cdn_url + str(i), "lnk")
        stream_links.append({
            "id": lnk_id,
            "name": f"Link {i+1}",
            "type": "hls",
            "default": i == 0,
            "url": cdn_url,
            "request_headers": [
                {"key": "Referer", "value": match["url"]},
                {"key": "User-Agent", "value": "Mozilla/5.0"}
            ]
        })

    channel = {
        "id": uid,
        "name": f"⚽ {match['name']}",
        "type": "single",
        "display": "thumbnail-only",
        "enable_detail": False,
        "labels": [
            {
                "text": "● Live",
                "position": "top-left",
                "color": "#00ffffff",
                "text_color": "#ff0000"
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
            "league": detail.get("league", ""),
            "team_a": match["name"].split(" vs ")[0] if " vs " in match["name"] else "",
            "team_b": match["name"].split(" vs ")[1] if " vs " in match["name"] else "",
            "logo_a": detail.get("logo_a", match.get("logo_a", "")),
            "logo_b": detail.get("logo_b", match.get("logo_b", "")),
            "thumb": detail.get("thumb", ""),
        }
    }

    return channel

def main():
    print("🔍 Đang lấy danh sách trận từ cakhiatv247...")
    matches = get_matches()
    print(f"✅ Tìm thấy {len(matches)} trận")

    channels = []
    for i, match in enumerate(matches):
        print(f"  [{i+1}/{len(matches)}] {match['name']}")
        detail = get_match_detail(match["url"])
        channel = build_channel(match, detail)
        channels.append(channel)
        time.sleep(0.5)

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
        "groups": [{
            "id": "live",
            "name": "🔴 Live",
            "display": "vertical",
            "grid_number": 2,
            "enable_detail": False,
            "channels": channels
        }]
    }

    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Xong! {len(channels)} kênh → output.json")

if __name__ == "__main__":
    main()
