# -*- coding: utf-8 -*-
"""
本機執行腳本：自動讀取同資料夾中「海盜隊超連結.txt」的連結清單，
抓取各網頁的 <title> 標題與頁面主標題，並儲存為 CSV 檔案（海盜隊網頁標題.csv）。

安裝必要套件（僅需執行一次）：
    pip install requests beautifulsoup4

執行方式：
    python scrape_myscore_titles-v3.py
"""

import csv
import html
import os
import re
import time
from urllib.parse import urlparse, parse_qs

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

INPUT_TXT_FILENAME = "海盜隊超連結.txt"
OUTPUT_CSV_FILENAME = "海盜隊網頁標題.csv"

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


def load_links_from_txt(txt_path: str) -> list[tuple[int, str, str]]:
    """從海盜隊超連結.txt 解析出 (編號, 連結文字, 網址) 清單"""
    if not os.path.exists(txt_path):
        raise FileNotFoundError(
            f"找不到輸入檔案：{txt_path}\n請確認「{INPUT_TXT_FILENAME}」與此程式放在同一個資料夾中。"
        )

    # 優先使用 utf-8-sig 讀取（相容含 BOM 的 UTF-8），若失敗則退回 cp950 (Big5)
    try:
        with open(txt_path, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        with open(txt_path, "r", encoding="cp950") as f:
            lines = f.readlines()

    item_pattern = re.compile(r"^\s*(\d+)\.\s*(.+?)\s*$")
    url_pattern = re.compile(r"^\s*(https?://\S+)\s*$")

    links: list[tuple[int, str, str]] = []
    current_idx: int | None = None
    current_title: str | None = None

    for line in lines:
        m_item = item_pattern.match(line)
        if m_item:
            current_idx = int(m_item.group(1))
            # 將 &#40; / &#41; 等 HTML 實體字元還原為正常括號
            current_title = html.unescape(m_item.group(2))
            continue

        m_url = url_pattern.match(line)
        if m_url and current_idx is not None and current_title is not None:
            links.append((current_idx, current_title, m_url.group(1)))
            current_idx = None
            current_title = None

    return links


def fetch_title(session: requests.Session, url: str) -> tuple[str, str]:
    """回傳 (<title>內容, 頁面主標題 h1/h2/h3)"""
    try:
        resp = session.get(url, headers=HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")

        title_tag = soup.find("title")
        html_title = html.unescape(title_tag.get_text(strip=True)) if title_tag else ""

        h_tag = soup.find(["h1", "h2", "h3"])
        main_heading = html.unescape(h_tag.get_text(" ", strip=True)) if h_tag else ""

        return html_title, main_heading
    except Exception as exc:
        return f"[抓取失敗] {exc}", ""


def save_to_csv(rows: list[dict], csv_path: str) -> None:
    """將抓取結果存成 UTF-8 with BOM 的 CSV 檔（Excel 開啟不會亂碼）"""
    fieldnames = ["編號", "原始連結文字", "網頁<title>標題", "頁面主標題", "game_id", "網址"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "編號": r["idx"],
                "原始連結文字": r["link_text"],
                "網頁<title>標題": r["html_title"],
                "頁面主標題": r["main_heading"],
                "game_id": r["game_id"],
                "網址": r["url"],
            })


def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    txt_path = os.path.join(script_dir, INPUT_TXT_FILENAME)
    csv_path = os.path.join(script_dir, OUTPUT_CSV_FILENAME)

    links = load_links_from_txt(txt_path)
    if not links:
        print(f"在「{INPUT_TXT_FILENAME}」中未解析到任何有效連結，請檢查檔案內容格式。")
        return

    session = requests.Session()
    results = []

    print(f"已從「{INPUT_TXT_FILENAME}」讀取 {len(links)} 筆連結，開始抓取 <title> 內容...\n")
    for idx, link_text, url in links:
        qs = parse_qs(urlparse(url).query)
        game_id = qs.get("game_id", [""])[0]

        html_title, main_heading = fetch_title(session, url)
        print(f"[{idx:02d}/{len(links)}] {link_text}  ==>  <title>: {html_title}")

        results.append({
            "idx": idx,
            "link_text": link_text,
            "html_title": html_title,
            "main_heading": main_heading,
            "game_id": game_id,
            "url": url,
        })
        time.sleep(0.3)

    save_to_csv(results, csv_path)
    print("\n" + "=" * 60)
    print(f"全部完成！已將 {len(results)} 筆結果儲存至 CSV 檔：")
    print(csv_path)


if __name__ == "__main__":
    main()
