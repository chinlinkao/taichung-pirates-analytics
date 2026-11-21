"""種子清單預處理模組。

讀取 data/海盜隊網頁標題.csv（遵守 encoding="utf-8-sig" 與繁體中文註解規範），
萃取聯賽與球隊維度資料。
"""

import csv
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any, Dict, List

DEFAULT_CSV_PATH = Path("data/海盜隊網頁標題.csv")


def extract_league_meta(title: str) -> Dict[str, Any]:
    """從標題中解析年份、賽季、賽制、組別與層級。"""
    # 提取年份：4 位數字
    m_year = re.search(r"(\d{4})", title)
    year = int(m_year.group(1)) if m_year else 2026

    # 賽季
    if "春季" in title:
        season = "春季"
    elif "秋季" in title:
        season = "秋季"
    else:
        season = "其他"

    # 賽制類型
    if "台灣大賽" in title:
        tournament_type = "台灣大賽"
    elif "季後賽" in title:
        tournament_type = "季後賽"
    else:
        tournament_type = "例行賽"

    # 年齡層級 (U8 / U10 / U12 / U15)
    m_age = re.search(r"(U(?:8|10|12|15))", title, re.IGNORECASE)
    age_group = m_age.group(1).upper() if m_age else "U12"

    # 分級 (大聯盟 / 小聯盟 / 一般)
    if "大聯盟" in title:
        division = "大聯盟"
    elif "小聯盟" in title:
        division = "小聯盟"
    else:
        division = "一般"

    return {
        "year": year,
        "season": season,
        "tournament_type": tournament_type,
        "age_group": age_group,
        "division": division,
    }


def classify_team_group(raw_link_text: str) -> str:
    """依原始連結文字分類分隊群組。

    - '台中海盜' -> 'U15海盜'
    - 含 '(白)' -> '白隊'
    - 含 '(黑)' -> '黑隊'
    - '台中小海盜' -> '海盜本隊'
    """
    text = raw_link_text.strip()
    if text == "台中海盜":
        return "U15海盜"
    if "(白)" in text:
        return "白隊"
    if "(黑)" in text:
        return "黑隊"
    return "海盜本隊"


def load_seeds(csv_path: Path | str = DEFAULT_CSV_PATH) -> List[Dict[str, Any]]:
    """讀取種子 CSV 並解析欄位。"""
    path = Path(csv_path)
    if not path.exists():
        fallback_path = Path("海盜隊網頁標題.csv")
        if fallback_path.exists():
            path = fallback_path
        else:
            raise FileNotFoundError(f"找不到種子 CSV: {path}")

    seeds: List[Dict[str, Any]] = []

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            csv_row_no = int(row["編號"].strip())
            raw_link_text = row["原始連結文字"].strip()
            raw_title = row.get("網頁<title>標題", "").strip()
            raw_url = row["網址"].strip()

            # 去除 #team-section
            clean_url = raw_url.split("#")[0]
            parsed_url = urlparse(clean_url)
            qs = parse_qs(parsed_url.query)

            game_id = int(qs.get("game_id", [row.get("game_id", 0)])[0])
            team_id = int(qs["team_id"][0])

            # 賽事完整名稱
            if " - " in raw_title:
                league_title = raw_title.split(" - ", 1)[1].strip()
            else:
                league_title = raw_title

            meta = extract_league_meta(raw_title)
            team_group = classify_team_group(raw_link_text)

            seeds.append(
                {
                    "csv_row_no": csv_row_no,
                    "league_id": game_id,
                    "team_id": team_id,
                    "team_name": raw_link_text,
                    "team_group": team_group,
                    "league_title": league_title,
                    "source_url": clean_url,
                    **meta,
                }
            )

    return seeds


if __name__ == "__main__":
    seeds = load_seeds()
    print(f"成功讀取 {len(seeds)} 筆種子資料。")
    for s in seeds[:3]:
        print(s)
