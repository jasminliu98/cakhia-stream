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
    """Lấy danh sách trận + match_id + blv_id từ trang chủ"""
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

        # Lấy tên 2 đội
        imgs = a.select("img[alt]")
        team_names = [
            i.get("alt", "") for i in imgs
            if i.get("alt") and i.get("alt") not in ["Bóng đá","Bóng rổ","Tennis","Cầu Lông","Billiards","Võ Thuật","Bóng chuyền","Pickleball"]
        ]

        # Lấy logo đội
        logos = [
            i.get("src","") for i in imgs
            if i.get("src","") and "soccer.svg" not in i.get("src","") and "icon" not in i.get("src","")
        ]

        # Lấy giờ
        text = a.get_text(" ", strip=True)
        time_match = re.search(r'\d{2}:\d{2}', text)
        match_time = time_match.group(0) if time_match else ""

        # Lấy BLV links (channel_id) từ các link ?blv=
        blv_links = re.findall(r'\?blv=(\d+)', str(a))

        name = f"{team_names[0]} vs {team_names[1]}" if len(team_names) >= 2 else text[:60]

        matches.append({
            "url": url,
            "match_id": match_id,
            "name": name,
            "time": match_time,
            "logo_a": logos[0] if len(logos) > 0 else "",
            "logo_b": logos[1] if len(logos) > 1 else "",
            "blv_ids": blv_links,
        })

    return matches

def get_streams(match_id, blv_ids):
    """Gọi cbox API để lấy link m3u8"""
    streams = []

    # Nếu không có BLV ID, thử channel_id mặc định
    if not blv_ids:
        blv_ids = ["0"]

    for blv_id in blv_ids[:3]:  # Tối đa 3 BLV
        try:
            url = f"{CBOX_URL}?match_id={match_id}&channel_id={blv_id}"
            res = requests.get(url, headers=HEADERS, timeout=10)

            # Tìm tất cả link m3u8
            # Decode unicode escape trước
            text = res.text.encode().decode('unicode_escape', errors='ignore')
            m3u8_links = re.findall(r'https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*', text)
            # Cũng tìm alilicloud
            alili_links = re.findall(r'https?://[^\s"\'<>\\]*alilicloud[^\s"\'<>\\]*', text)

            all_links = list(dict.fromkeys(m3u8_links + alili_links))
            streams.extend(all_links)
        except Exception as e:
            print(f"    Lỗi cbox {match_id}/{blv_id}: {e}")
        time.sleep(0.2)

    return list(dict.fromkeys(streams))  # unique

def get_match_detail(match_url):
    """Lấy thêm logo, giải đấu từ trang trận"""
    try:
        res = requests.get(match_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")

        # Logo từ cdn.rapid-api hoặc taoxanh
        logos = [
            i.get("src","") for i in soup.select("img[src]")
            if any(x in i.get("src","") for x in ["rapid-api","taoxanh.biz/live-phogatv/football"])
        ]

        # Tên giải từ breadcrumb hoặc title
        title = soup.find("title")
        league = ""
        if title:
            t = title.get_text()
            # "Xem trực tiếp X vs Y ... GiaiDau"
            m = re.search(r'(?:Spanish|English|German|French|Italian|V-League|Premier|Liga|Bundesliga|Serie|Ligue|Champions)[^\|]+', t)
            if m:
                league = m.group(0).strip()

        thumb = ""
        og = soup.find("meta", property="og:image")
        if og:
            thumb = og.get("content", "")

        return {
            "league": league,
            "logo_a": logos[0] if len(logos) > 0 else "",
            "logo_b": logos[1] if len(logos) > 1 else "",
            "thumb": thumb,
        }
    except:
        return {"league": "", "logo_a": "", "logo_b": "", "thumb": ""}

def build_channel(match, detail, streams):
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
                {"key": "Referer", "value": match["url"]},
                {"key": "User-Agent", "value": "Mozilla/5.0"}
            ]
        })

    return {
        "id": uid,
        "name": f"⚽ {match['name']}",
        "type": "single",
        "display": "thumbnail-only",
        "enable_detail": False,
        "labels": [{"text": "● Live", "position": "top-left",
                    "color": "#00ffffff", "text_color": "#ff0000"}],
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
            "team_a": match["name"].split(" vs ")[0] if " vs " in match["name"] else match["name"],
            "team_b": match["name"].split(" vs ")[1] if " vs " in match["name"] else "",
            "logo_a": detail.get("logo_a") or match.get("logo_a", ""),
            "logo_b": detail.get("logo_b") or match.get("logo_b", ""),
            "thumb": detail.get("thumb", ""),
        }
    }

def main():
    print("🔍 Lấy danh sách trận từ cakhiatv247...")
    matches = get_matches()
    print(f"✅ Tìm thấy {len(matches)} trận\n")

    channels = []
    for i, match in enumerate(matches):
        print(f"[{i+1}/{len(matches)}] {match['name']} (ID: {match['match_id']})")

        # Lấy stream từ cbox API
        streams = get_streams(match["match_id"], match["blv_ids"])
        print(f"    → {len(streams)} link stream")

        if not streams:
            print(f"    ⚠️ Bỏ qua (không có stream)")
            continue

        # Lấy detail (logo, giải)
        detail = get_match_detail(match["url"])

        channel = build_channel(match, detail, streams)
        channels.append(channel)
        time.sleep(0.3)

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
