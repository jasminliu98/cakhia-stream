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

        # LIVE: class stream_m_live
        card_class = " ".join(card.get("class", []))
        is_live = "stream_m_live" in card_class

        # Logo: lấy tất cả img có data-src chứa /team/, bỏ /league/
        team_imgs = [
            i for i in card.select("img[data-src]")
            if "/team/" in i.get("data-src", "") and "/league/" not in i.get("data-src", "")
        ]
        logo_a = team_imgs[0].get("data-src", "") if len(team_imgs) > 0 else ""
        logo_b = team_imgs[1].get("data-src", "") if len(team_imgs) > 1 else ""
        team_a = team_imgs[0].get("alt", "") if len(team_imgs) > 0 else ""
        team_b = team_imgs[1].get("alt", "") if len(team_imgs) > 1 else ""

        # Giải đấu
        league_tag = card.select_one("span.s_by_name")
        league = league_tag.get_text(strip=True) if league_tag else ""

        # Giờ đấu
        time_tag = card.select_one("span.font-mono")
        match_time = time_tag.get_text(strip=True) if time_tag else ""

        # BLV
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

    blv_names = ", ".join([b["name"] for b in match["blv_list"]]) if match["blv_list"] else ""
    display_name = match["name"]
    if match["time"]:
        display_name = f"{match['name']} ({match['time']})"

    label_text  = "● LIVE" if match["is_live"] else f"🕐 {match['time']}"
    label_color = "#ff4444" if match["is_live"] else "#aaaaaa"

    return {
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
        print(f"  logo_a: {match['logo_a'][:60] if match['logo_a'] else 'TRONG'}")
        print(f"  logo_b: {match['logo_b'][:60] if match['logo_b'] else 'TRONG'}")
        streams = get_streams(match["match_id"], match["blv_list"])
        print(f"  stream: {len(streams)} link")
        if not streams:
            continue
        live_channels.append(build_channel(match, streams))
        time.sleep(0.3)

    for match in upcoming_matches:
        upcoming_channels.append(build_channel(match, []))

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
