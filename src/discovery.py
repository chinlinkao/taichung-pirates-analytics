"""自動探索與種子清單維護模組 (src/discovery.py)。

整合原 find_pirates.py 與 scrape_myscore_titles-v3.py 邏輯：
1. 遵守爬蟲規範：單線程循序請求、每次間隔 >= 1.5 秒、以 utf-8-sig 存取 CSV。
2. 走訪 myscore.games 探索包含「海盜」的球隊連結。
3. 比對 data/海盜隊網頁標題.csv 中的現有網址，僅對新發現的賽事連結抓取網頁標題。
4. 自動增量追加至 CSV，完全省去中間暫存檔與人工作業。
"""

import csv
import html
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any, Dict, List, Set, Tuple

import httpx
from bs4 import BeautifulSoup

DEFAULT_CSV_PATH = Path("data/海盜隊網頁標題.csv")
BASE_URL = "https://myscore.games"
INDEX_URL = "https://myscore.games/index.php"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://myscore.games/index.php",
}


def clean_link_text(text: str) -> str:
    """清理 HTML 標籤與多餘空白。"""
    clean = re.sub(r"<[^>]+>", "", text).strip()
    return html.unescape(clean)


def extract_links_from_html(html_content: str, base_url: str = BASE_URL) -> List[Tuple[str, str]]:
    """從 HTML 內容中提取所有超連結 (絕對網址, 連結文字)。"""
    pattern = r'<a\s[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>'
    links = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
    results = []
    for href, text in links:
        cleaned_text = clean_link_text(text)
        if href.startswith("http"):
            full_url = href
        elif href.startswith("/"):
            full_url = BASE_URL + href
        else:
            full_url = base_url.rstrip("/") + "/" + href.lstrip("/")
        results.append((full_url, cleaned_text))
    return results


def fetch_page(client: httpx.Client, url: str) -> str:
    """發送請求並回傳文字，並強制間隔 1.5 秒。"""
    resp = client.get(url)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    time.sleep(1.5)
    return resp.text


def extract_titles_from_html(html_text: str) -> Tuple[str, str]:
    """從球隊頁面解析 <title> 標題與頁面主標題。"""
    soup = BeautifulSoup(html_text, "html.parser")

    # 1. <title> 標籤
    title_tag = soup.find("title")
    html_title = title_tag.get_text(strip=True) if title_tag else ""

    # 2. 頁面主標題
    heading = ""
    for sel in ["h1", "h2", ".title", ".header"]:
        tag = soup.select_one(sel)
        if tag and tag.get_text(strip=True):
            heading = tag.get_text(strip=True)
            break
    if not heading:
        heading = "MyScore."

    return html_title, heading


def get_existing_urls(csv_path: Path) -> Tuple[Set[str], int]:
    """讀取現有 CSV 內的網址與當前最大編號。"""
    existing_urls = set()
    max_idx = 0
    if not csv_path.exists():
        return existing_urls, max_idx

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = row.get("網址", "").strip()
            # 正規化：去除 #team-section 與結尾空白
            clean_url = url.split("#")[0].strip()
            if clean_url:
                existing_urls.add(clean_url)
            try:
                idx = int(row.get("編號", 0))
                if idx > max_idx:
                    max_idx = idx
            except ValueError:
                pass
    return existing_urls, max_idx


def discover_pirate_links(
    csv_path: Path = DEFAULT_CSV_PATH,
) -> List[Dict[str, Any]]:
    """自動探索 myscore.games 賽事，檢索新的海盜隊連結並追加到 CSV。

    回傳：新增的項目清單
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    existing_urls, max_idx = get_existing_urls(csv_path)

    print(f"[*] 目前種子清單已有 {len(existing_urls)} 個賽事網址 (最大編號: {max_idx})。")
    print(f"[*] 正在連線 {INDEX_URL} 探索所有聯賽...")

    new_entries: List[Dict[str, Any]] = []

    with httpx.Client(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        try:
            index_html = fetch_page(client, INDEX_URL)
        except Exception as e:
            print(f"[!] 無法取得首頁內容: {e}")
            return []

        # 取得所有比賽與聯賽連結，並智慧過濾與「海盜」或「台中就是棒/台灣大賽」相關的賽程頁面
        all_index_links = extract_links_from_html(index_html, BASE_URL)
        game_links: Dict[str, str] = {}
        for link, text in all_index_links:
            if "game_id=" in link and "show_text.php" not in link:
                clean_link = link.split("#")[0]
                # 排除其他無關縣市 (如臺北、新北、桃園、新竹、台南、高雄等其他聯盟)
                is_irrelevant = any(reg in text for reg in ["臺北", "台北", "新北", "桃園", "新竹", "臺南", "台南", "高雄", "花蓮", "宜蘭", "苗栗", "彰化", "嘉義", "屏東"])
                is_target = ("臺中" in text or "台中" in text or "台灣大賽" in text or "海盜" in text)
                if is_target or not is_irrelevant:
                    game_links[clean_link] = text

        print(f"[*] 經智慧比對，鎖定 {len(game_links)} 個相關賽程/聯賽頁面，開始檢索「海盜」球隊...")

        candidate_links: Dict[str, str] = {}  # url -> link_text

        # 先檢查首頁本身
        for url, text in all_index_links:
            if "show_text.php" in url:
                continue
            if "海盜" in text and "team_id" in url:
                clean = url.split("#")[0]
                if clean not in existing_urls:
                    candidate_links[clean] = text

        # 循序檢查篩選後的目標賽事頁
        for i, (g_url, g_title) in enumerate(sorted(game_links.items()), 1):
            try:
                g_html = fetch_page(client, g_url)
                for url, text in extract_links_from_html(g_html, BASE_URL):
                    if "show_text.php" in url:
                        continue
                    if "海盜" in text and "team_id" in url:
                        clean = url.split("#")[0]
                        if clean not in existing_urls and clean not in candidate_links:
                            candidate_links[clean] = text
                            print(f"    >>> 探索到新球隊連結: {text} -> {clean}")
            except Exception as e:
                print(f"    [!] 抓取賽程失敗 ({g_url}): {e}")

        if not candidate_links:
            print("[+] 未發現新的海盜隊賽事網址，資料清單已是最新狀態！")
            return []

        print(f"\n[*] 發現 {len(candidate_links)} 個全新賽事，開始抓取網頁標題資訊...")
        curr_idx = max_idx

        # 對新網址抓取詳細標題
        for clean_url, link_text in sorted(candidate_links.items()):
            curr_idx += 1
            qs = parse_qs(urlparse(clean_url).query)
            game_id = qs.get("game_id", [""])[0]

            full_fetch_url = clean_url + "#team-section"
            try:
                page_html = fetch_page(client, full_fetch_url)
                html_title, main_heading = extract_titles_from_html(page_html)
            except Exception as e:
                print(f"    [!] 抓取標題失敗 ({clean_url}): {e}")
                html_title = f"{link_text} 球隊紀錄"
                main_heading = "MyScore."

            entry = {
                "編號": curr_idx,
                "原始連結文字": link_text,
                "網頁<title>標題": html_title,
                "頁面主標題": main_heading,
                "game_id": game_id,
                "網址": full_fetch_url,
            }
            new_entries.append(entry)
            print(f"    [+{curr_idx}] 已收錄: {link_text} | {html_title}")

        # 追加寫入 CSV
        fieldnames = ["編號", "原始連結文字", "網頁<title>標題", "頁面主標題", "game_id", "網址"]
        file_exists = csv_path.exists() and csv_path.stat().st_size > 0

        with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            for entry in new_entries:
                writer.writerow(entry)

        # 同步更新根目錄 CSV (若有需要)
        root_csv = Path("海盜隊網頁標題.csv")
        if root_csv.exists() and root_csv.resolve() != csv_path.resolve():
            with open(root_csv, "a", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                for entry in new_entries:
                    writer.writerow(entry)

        print(f"[SUCCESS] 成功將 {len(new_entries)} 筆新賽事寫入 {csv_path}！")

    return new_entries


if __name__ == "__main__":
    discover_pirate_links()
