"""HTML DOM 解析與入庫模組 (src/parse.py)。

遵守台中小海盜數據專案規範 (AGENTS.md) 與 IMPLEMENTATION_PLAN.md：
- 一律只讀取本地快取 data/raw_html/{league_id}_{team_id}.html
- 球員唯一識別優先使用 site_player_id (id:{site_player_id})，次為 {masked_name}_{birth_ym}
- 投球局數入庫一律轉換為整數出局數 outs = round(float(ip) * 3)
- 賽程表格強制去重（僅取第一個出現的表格容器）
- 單隊資料庫寫入以單一 Transaction 包裝，保證冪等性 (Idempotent)
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

# 支援直接執行腳本時能匯入根目錄模組
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup

from src.db import DEFAULT_DB_PATH, get_db_connection, init_db
from src.seed_loader import DEFAULT_CSV_PATH, load_seeds

DEFAULT_CACHE_DIR = Path("data/raw_html")


def parse_coaches(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    """提取教練團資訊（領隊、總教練、管理、教練）。"""
    res = {
        "leader": None,
        "head_coach": None,
        "manager": None,
        "coaches": None,
    }

    # 尋找包含「領隊」或「總教練」的表格
    for tbl in soup.find_all("table"):
        text = tbl.get_text()
        if "領隊" in text or "總教練" in text:
            cells = [c.get_text(strip=True) for c in tbl.find_all(["td", "th"])]
            for i in range(len(cells) - 1):
                key = cells[i].replace("：", "").replace(":", "").strip()
                val = cells[i + 1].strip()
                if key == "領隊":
                    res["leader"] = val or None
                elif key == "總教練":
                    res["head_coach"] = val or None
                elif key == "管理":
                    res["manager"] = val or None
                elif key == "教練":
                    res["coaches"] = val or None
            break

    return res


def parse_roster(
    soup: BeautifulSoup, team_id: int
) -> Tuple[List[Dict[str, Any]], Dict[Tuple[str, str], str], Dict[str, List[str]]]:
    """解析球員名冊表格，產出名冊資料、(背號, 姓名) -> UID 對照表、姓名 -> UID 清單。"""
    roster_list: List[Dict[str, Any]] = []
    roster_lookup: Dict[Tuple[str, str], str] = {}
    name_lookup: Dict[str, List[str]] = {}

    roster_table = None
    for tbl in soup.find_all("table"):
        txt = tbl.get_text()
        if "背號" in txt and "姓名" in txt:
            roster_table = tbl
            break

    if not roster_table:
        return roster_list, roster_lookup, name_lookup

    for tr in roster_table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue

        jersey_number = tds[0].get_text(strip=True)
        # 姓名格可能有 form 或 button
        name_td = tds[1]
        position = tds[2].get_text(strip=True)
        birth_ym = tds[3].get_text(strip=True) or None

        # 嘗試尋找 player_id
        site_player_id: Optional[int] = None
        masked_name = ""

        # 優先從 form 內尋找
        form = name_td.find("form")
        if form:
            inp_id = form.find("input", {"name": "player_id"})
            if inp_id and inp_id.get("value"):
                try:
                    site_player_id = int(inp_id["value"].strip())
                except ValueError:
                    pass
            btn = form.find("button")
            if btn:
                masked_name = btn.get_text(strip=True)

        if not masked_name:
            # 嘗試找 a 標籤
            a_tag = name_td.find("a")
            if a_tag:
                masked_name = a_tag.get_text(strip=True)
                href = a_tag.get("href", "")
                m = re.search(r"player_id=(\d+)", href)
                if m:
                    site_player_id = int(m.group(1))
            else:
                masked_name = name_td.get_text(strip=True)

        masked_name = re.sub(r"\s+", "", masked_name)

        # 決定 player_uid 鐵則：以 (遮罩姓名, 出生年月) 作為跨屆唯一歸戶鍵
        if birth_ym:
            player_uid = f"{masked_name}_{birth_ym}"
        elif site_player_id is not None:
            player_uid = f"id:{site_player_id}"
        else:
            player_uid = f"{masked_name}_team{team_id}_{jersey_number}"

        item = {
            "player_uid": player_uid,
            "site_player_id": site_player_id,
            "masked_name": masked_name,
            "birth_ym": birth_ym,
            "jersey_number": jersey_number,
            "position": position,
        }
        roster_list.append(item)

        roster_lookup[(jersey_number, masked_name)] = player_uid
        name_lookup.setdefault(masked_name, []).append(player_uid)

    return roster_list, roster_lookup, name_lookup


def parse_matches(
    soup: BeautifulSoup, team_id: int, league_id: int, year: int, season: str
) -> List[Dict[str, Any]]:
    """解析賽程及結果表格（僅取第一個出現的表格，防止 DOM 重複渲染）。"""
    matches_list: List[Dict[str, Any]] = []

    schedule_table = None
    for tbl in soup.find_all("table"):
        txt = tbl.get_text()
        if "日期" in txt and "時間" in txt and "賽事" in txt:
            schedule_table = tbl
            break

    if not schedule_table:
        return matches_list

    for tr in schedule_table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        match_date = tds[0].get_text(strip=True)
        match_time = tds[1].get_text(strip=True)
        game_cell = tds[2]
        venue = tds[3].get_text(strip=True) or None
        links_cell = tds[4]

        # 解析賽事球隊與比分
        raw_text = game_cell.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]

        away_team = ""
        home_team = ""
        away_score: Optional[int] = None
        home_score: Optional[int] = None

        if lines:
            teams_line = lines[0]
            if " vs. " in teams_line:
                away_team, home_team = teams_line.split(" vs. ", 1)
            elif " vs " in teams_line:
                away_team, home_team = teams_line.split(" vs ", 1)
            else:
                away_team = teams_line
                home_team = ""

            away_team = away_team.strip()
            home_team = home_team.strip()

            score_line = lines[1] if len(lines) > 1 else ""
            if ":" in score_line:
                s_parts = score_line.split(":", 1)
                try:
                    away_score = int(s_parts[0].strip())
                    home_score = int(s_parts[1].strip())
                except ValueError:
                    away_score = None
                    home_score = None

        # 推導 match_date_iso (處理秋季跨年 1/2/3 月)
        match_date_iso = None
        m_date = re.match(r"^(\d{1,2})/(\d{1,2})$", match_date)
        if m_date:
            month = int(m_date.group(1))
            day = int(m_date.group(2))
            iso_year = year + 1 if season == "秋季" and month in (1, 2, 3) else year
            match_date_iso = f"{iso_year:04d}-{month:02d}-{day:02d}"

        # 提取三個單場連結
        boxscore_url = None
        pbp_url = None
        summary_url = None

        for a in links_cell.find_all("a", href=True):
            a_txt = a.get_text(strip=True)
            href = urljoin("https://myscore.games/", a["href"].strip())
            if "攻守數據" in a_txt:
                boxscore_url = href
            elif "文字紀錄" in a_txt:
                pbp_url = href
            elif "戰況表" in a_txt:
                summary_url = href

        matches_list.append(
            {
                "team_id": team_id,
                "league_id": league_id,
                "match_date": match_date,
                "match_date_iso": match_date_iso,
                "match_time": match_time,
                "away_team": away_team,
                "home_team": home_team,
                "away_score": away_score,
                "home_score": home_score,
                "venue": venue,
                "boxscore_url": boxscore_url,
                "pbp_url": pbp_url,
                "summary_url": summary_url,
            }
        )

    return matches_list


def resolve_player(
    raw_player: str,
    roster_lookup: Dict[Tuple[str, str], str],
    name_lookup: Dict[str, List[str]],
    team_id: int,
    extra_players: Dict[str, Dict[str, Any]],
) -> Tuple[str, str, str]:
    """從 Player 欄位 (如 '66 蔡〇宇') 解析出 (jersey_number, masked_name, player_uid)。"""
    m = re.match(r"^\s*(\d*)\s*(.+?)\s*$", raw_player)
    if m:
        jersey_number = m.group(1).strip()
        masked_name = m.group(2).strip()
    else:
        jersey_number = ""
        masked_name = raw_player.strip()

    masked_name = re.sub(r"\s+", "", masked_name)

    # 1. 優先精準比對 (背號, 姓名)
    if (jersey_number, masked_name) in roster_lookup:
        return jersey_number, masked_name, roster_lookup[(jersey_number, masked_name)]

    # 2. 特殊處理 U8 攻方教練拋打
    if "攻方教練" in masked_name or "不計投球成績" in masked_name:
        coach_uid = "coach_pitch_888"
        extra_players[coach_uid] = {
            "player_uid": coach_uid,
            "site_player_id": None,
            "masked_name": masked_name,
            "birth_ym": None,
        }
        return jersey_number or "888", masked_name, coach_uid

    # 3. 備援：若該隊名冊僅有一位同名球員
    candidates = name_lookup.get(masked_name, [])
    if len(candidates) == 1:
        return jersey_number, masked_name, candidates[0]

    # 4. 罕見漏登錄：新建獨立識別 UID
    fallback_uid = f"{masked_name}_team{team_id}_{jersey_number}"
    extra_players[fallback_uid] = {
        "player_uid": fallback_uid,
        "site_player_id": None,
        "masked_name": masked_name,
        "birth_ym": None,
    }
    return jersey_number, masked_name, fallback_uid


def parse_batting_stats(
    soup: BeautifulSoup,
    team_id: int,
    roster_lookup: Dict[Tuple[str, str], str],
    name_lookup: Dict[str, List[str]],
    extra_players: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """解析球隊打者表現表格。"""
    batting_list: List[Dict[str, Any]] = []

    bat_table = None
    for tbl in soup.find_all("table"):
        txt = tbl.get_text()
        if ("打者成績" in txt or "PA" in txt) and "OBP" in txt:
            bat_table = tbl
            break

    if not bat_table:
        return batting_list

    # 找出欄位標題所在的 tr
    header_tr_idx = -1
    headers: List[str] = []
    trs = bat_table.find_all("tr")
    for idx, tr in enumerate(trs):
        th_texts = [c.get_text(strip=True).replace("Ｇ", "G") for c in tr.find_all(["th", "td"])]
        if "PA" in th_texts and "AB" in th_texts:
            headers = th_texts
            header_tr_idx = idx
            break

    if header_tr_idx == -1:
        return batting_list

    # 建立欄位索引字典
    col_map = {col: i for i, col in enumerate(headers)}

    def get_int(row_cells: List[str], col_name: str, default: int = 0) -> int:
        idx = col_map.get(col_name)
        if idx is not None and idx < len(row_cells):
            val = row_cells[idx].strip()
            if val and val != "-":
                try:
                    return int(val)
                except ValueError:
                    pass
        return default

    def get_float(row_cells: List[str], col_name: str) -> Optional[float]:
        idx = col_map.get(col_name)
        if idx is not None and idx < len(row_cells):
            val = row_cells[idx].strip()
            if val and val != "-":
                try:
                    return float(val)
                except ValueError:
                    pass
        return None

    for tr in trs[header_tr_idx + 1 :]:
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if not cells or not cells[0]:
            continue

        raw_player = cells[col_map.get("Player", 0)]
        jersey_number, masked_name, player_uid = resolve_player(
            raw_player=raw_player,
            roster_lookup=roster_lookup,
            name_lookup=name_lookup,
            team_id=team_id,
            extra_players=extra_players,
        )

        stat = {
            "team_id": team_id,
            "player_uid": player_uid,
            "jersey_number": jersey_number,
            "g": get_int(cells, "G"),
            "pa": get_int(cells, "PA"),
            "ab": get_int(cells, "AB"),
            "h": get_int(cells, "H"),
            "doubles": get_int(cells, "2B"),
            "triples": get_int(cells, "3B"),
            "hr": get_int(cells, "HR"),
            "bb": get_int(cells, "BB"),
            "so": get_int(cells, "SO"),
            "rbi": get_int(cells, "RBI"),
            "r": get_int(cells, "R"),
            "sb_top10": None,  # 後續由 Top 10 回填
            "site_obp": get_float(cells, "OBP"),
            "site_slg": get_float(cells, "SLG"),
            "site_avg": get_float(cells, "AVG"),
        }
        batting_list.append(stat)

    return batting_list


def parse_pitching_stats(
    soup: BeautifulSoup,
    team_id: int,
    roster_lookup: Dict[Tuple[str, str], str],
    name_lookup: Dict[str, List[str]],
    extra_players: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """解析球隊投手表現表格。"""
    pitching_list: List[Dict[str, Any]] = []

    pitch_table = None
    for tbl in soup.find_all("table"):
        txt = tbl.get_text()
        if ("投手成績" in txt or "ERA" in txt) and "SV" in txt:
            pitch_table = tbl
            break

    if not pitch_table:
        return pitching_list

    header_tr_idx = -1
    headers: List[str] = []
    trs = pitch_table.find_all("tr")
    for idx, tr in enumerate(trs):
        th_texts = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
        if "IP" in th_texts and "ERA" in th_texts:
            headers = th_texts
            header_tr_idx = idx
            break

    if header_tr_idx == -1:
        return pitching_list

    col_map = {col: i for i, col in enumerate(headers)}

    def get_int(row_cells: List[str], col_name: str, default: int = 0) -> int:
        idx = col_map.get(col_name)
        if idx is not None and idx < len(row_cells):
            val = row_cells[idx].strip()
            if val and val != "-":
                try:
                    return int(val)
                except ValueError:
                    pass
        return default

    def get_float(row_cells: List[str], col_name: str) -> Optional[float]:
        idx = col_map.get(col_name)
        if idx is not None and idx < len(row_cells):
            val = row_cells[idx].strip()
            if val and val != "-":
                try:
                    return float(val)
                except ValueError:
                    pass
        return None

    for tr in trs[header_tr_idx + 1 :]:
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if not cells or not cells[0]:
            continue

        raw_player = cells[col_map.get("Player", 0)]
        jersey_number, masked_name, player_uid = resolve_player(
            raw_player=raw_player,
            roster_lookup=roster_lookup,
            name_lookup=name_lookup,
            team_id=team_id,
            extra_players=extra_players,
        )

        ip_idx = col_map.get("IP")
        ip_raw = cells[ip_idx].strip() if ip_idx is not None and ip_idx < len(cells) else ""
        outs = 0
        if ip_raw and ip_raw != "-":
            try:
                outs = round(float(ip_raw) * 3)
            except ValueError:
                outs = 0

        stat = {
            "team_id": team_id,
            "player_uid": player_uid,
            "jersey_number": jersey_number,
            "w": get_int(cells, "W"),
            "l": get_int(cells, "L"),
            "sv": get_int(cells, "SV"),
            "g": get_int(cells, "G"),
            "outs": outs,
            "ip_raw": ip_raw or None,
            "ab": get_int(cells, "AB"),
            "h": get_int(cells, "H"),
            "doubles": get_int(cells, "2B"),
            "triples": get_int(cells, "3B"),
            "hr": get_int(cells, "HR"),
            "bb": get_int(cells, "BB"),
            "so": get_int(cells, "SO"),
            "r": get_int(cells, "R"),
            "er": get_int(cells, "ER"),
            "site_opp_avg": get_float(cells, "AVG"),
            "site_era": get_float(cells, "ERA"),
        }
        pitching_list.append(stat)

    return pitching_list


def parse_top10_sb(
    soup: BeautifulSoup,
    team_id: int,
    name_lookup: Dict[str, List[str]],
    site_id_to_uid: Dict[int, str],
) -> Dict[str, int]:
    """解析頁尾 Top 10 - Batting 盜壘排行榜，產出 player_uid -> sb 數值對照字典。"""
    sb_dict: Dict[str, int] = {}

    sb_table = None
    for tbl in soup.find_all("table"):
        txt = tbl.get_text()
        if "盜壘數" in txt and "球員" in txt:
            sb_table = tbl
            break

    if not sb_table:
        return sb_dict

    for tr in sb_table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue

        player_td = tds[1]
        team_name = tds[2].get_text(strip=True)
        sb_val_str = tds[3].get_text(strip=True)

        try:
            sb_val = int(sb_val_str)
        except ValueError:
            continue

        # 優先從表單取 player_id
        form = player_td.find("form")
        site_player_id = None
        masked_name = ""
        if form:
            inp = form.find("input", {"name": "player_id"})
            if inp and inp.get("value"):
                try:
                    site_player_id = int(inp["value"])
                except ValueError:
                    pass
            btn = form.find("button")
            if btn:
                masked_name = btn.get_text(strip=True)

        if not masked_name:
            masked_name = player_td.get_text(strip=True)

        masked_name = re.sub(r"\s+", "", masked_name)

        if site_player_id is not None and site_player_id in site_id_to_uid:
            sb_dict[site_id_to_uid[site_player_id]] = sb_val
        elif masked_name in name_lookup and len(name_lookup[masked_name]) == 1:
            sb_dict[name_lookup[masked_name][0]] = sb_val

    return sb_dict


def parse_and_store_team(
    seed: Dict[str, Any],
    conn: sqlite3.Connection,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> None:
    """解析單一球隊快取 HTML 並透過 Transaction 寫入 SQLite。"""
    html_path = cache_dir / f"{seed['league_id']}_{seed['team_id']}.html"
    if not html_path.exists():
        print(f"[!] 找不到快取檔案: {html_path}")
        return

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "lxml")

    # 1. 教練團
    coach_info = parse_coaches(soup)

    # 2. 名冊
    extra_players: Dict[str, Dict[str, Any]] = {}
    roster_list, roster_lookup, name_lookup = parse_roster(soup, seed["team_id"])

    # 3. 賽程及結果
    matches_list = parse_matches(
        soup=soup,
        team_id=seed["team_id"],
        league_id=seed["league_id"],
        year=seed["year"],
        season=seed["season"],
    )

    # 4. 打者表現
    batting_list = parse_batting_stats(
        soup=soup,
        team_id=seed["team_id"],
        roster_lookup=roster_lookup,
        name_lookup=name_lookup,
        extra_players=extra_players,
    )

    # 5. 投手表現
    pitching_list = parse_pitching_stats(
        soup=soup,
        team_id=seed["team_id"],
        roster_lookup=roster_lookup,
        name_lookup=name_lookup,
        extra_players=extra_players,
    )

    # 6. Top 10 盜壘補充
    site_id_to_uid = {
        r["site_player_id"]: r["player_uid"]
        for r in roster_list
        if r.get("site_player_id") is not None
    }
    sb_dict = parse_top10_sb(soup, seed["team_id"], name_lookup, site_id_to_uid)
    for b in batting_list:
        if b["player_uid"] in sb_dict:
            b["sb_top10"] = sb_dict[b["player_uid"]]

    last_fetched_at = datetime.fromtimestamp(html_path.stat().st_mtime, tz=timezone.utc).isoformat()

    # 執行資料庫事務寫入
    with conn:
        # A. leagues 表 Upsert
        conn.execute(
            """
            INSERT INTO leagues (league_id, league_title, year, season, tournament_type, age_group, division)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(league_id) DO UPDATE SET
                league_title=excluded.league_title,
                year=excluded.year,
                season=excluded.season,
                tournament_type=excluded.tournament_type,
                age_group=excluded.age_group,
                division=excluded.division;
            """,
            (
                seed["league_id"],
                seed["league_title"],
                seed["year"],
                seed["season"],
                seed["tournament_type"],
                seed["age_group"],
                seed["division"],
            ),
        )

        # B. teams 表 Upsert
        conn.execute(
            """
            INSERT INTO teams (
                team_id, league_id, csv_row_no, team_name, team_group,
                leader, head_coach, manager, coaches, source_url, last_fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(team_id) DO UPDATE SET
                league_id=excluded.league_id,
                csv_row_no=excluded.csv_row_no,
                team_name=excluded.team_name,
                team_group=excluded.team_group,
                leader=excluded.leader,
                head_coach=excluded.head_coach,
                manager=excluded.manager,
                coaches=excluded.coaches,
                source_url=excluded.source_url,
                last_fetched_at=excluded.last_fetched_at;
            """,
            (
                seed["team_id"],
                seed["league_id"],
                seed["csv_row_no"],
                seed["team_name"],
                seed["team_group"],
                coach_info["leader"],
                coach_info["head_coach"],
                coach_info["manager"],
                coach_info["coaches"],
                seed["source_url"],
                last_fetched_at,
            ),
        )

        # C. players 表寫入 (含 extra_players)
        all_players_to_insert = {p["player_uid"]: p for p in roster_list}
        all_players_to_insert.update(extra_players)

        for p in all_players_to_insert.values():
            conn.execute(
                """
                INSERT INTO players (player_uid, site_player_id, masked_name, birth_ym)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_uid) DO UPDATE SET
                    site_player_id=COALESCE(players.site_player_id, excluded.site_player_id),
                    birth_ym=COALESCE(players.birth_ym, excluded.birth_ym);
                """,
                (p["player_uid"], p.get("site_player_id"), p["masked_name"], p.get("birth_ym")),
            )

        # D. team_rosters 表寫入
        for r in roster_list:
            conn.execute(
                """
                INSERT INTO team_rosters (team_id, player_uid, jersey_number, position)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(team_id, player_uid) DO UPDATE SET
                    jersey_number=excluded.jersey_number,
                    position=excluded.position;
                """,
                (seed["team_id"], r["player_uid"], r["jersey_number"], r["position"]),
            )

        # E. matches 表寫入
        for m in matches_list:
            conn.execute(
                """
                INSERT INTO matches (
                    team_id, league_id, match_date, match_date_iso, match_time,
                    away_team, home_team, away_score, home_score, venue,
                    boxscore_url, pbp_url, summary_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id, match_date, match_time, away_team, home_team) DO UPDATE SET
                    away_score=excluded.away_score,
                    home_score=excluded.home_score,
                    venue=excluded.venue,
                    boxscore_url=excluded.boxscore_url,
                    pbp_url=excluded.pbp_url,
                    summary_url=excluded.summary_url;
                """,
                (
                    m["team_id"],
                    m["league_id"],
                    m["match_date"],
                    m["match_date_iso"],
                    m["match_time"],
                    m["away_team"],
                    m["home_team"],
                    m["away_score"],
                    m["home_score"],
                    m["venue"],
                    m["boxscore_url"],
                    m["pbp_url"],
                    m["summary_url"],
                ),
            )

        # F. team_batting_stats 表寫入
        for b in batting_list:
            conn.execute(
                """
                INSERT INTO team_batting_stats (
                    team_id, player_uid, jersey_number, g, pa, ab, h,
                    doubles, triples, hr, bb, so, rbi, r, sb_top10,
                    site_obp, site_slg, site_avg
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id, player_uid) DO UPDATE SET
                    jersey_number=excluded.jersey_number,
                    g=excluded.g,
                    pa=excluded.pa,
                    ab=excluded.ab,
                    h=excluded.h,
                    doubles=excluded.doubles,
                    triples=excluded.triples,
                    hr=excluded.hr,
                    bb=excluded.bb,
                    so=excluded.so,
                    rbi=excluded.rbi,
                    r=excluded.r,
                    sb_top10=excluded.sb_top10,
                    site_obp=excluded.site_obp,
                    site_slg=excluded.site_slg,
                    site_avg=excluded.site_avg;
                """,
                (
                    b["team_id"],
                    b["player_uid"],
                    b["jersey_number"],
                    b["g"],
                    b["pa"],
                    b["ab"],
                    b["h"],
                    b["doubles"],
                    b["triples"],
                    b["hr"],
                    b["bb"],
                    b["so"],
                    b["rbi"],
                    b["r"],
                    b["sb_top10"],
                    b["site_obp"],
                    b["site_slg"],
                    b["site_avg"],
                ),
            )

        # G. team_pitching_stats 表寫入
        for pt in pitching_list:
            conn.execute(
                """
                INSERT INTO team_pitching_stats (
                    team_id, player_uid, jersey_number, w, l, sv, g,
                    outs, ip_raw, ab, h, doubles, triples, hr, bb,
                    so, r, er, site_opp_avg, site_era
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id, player_uid) DO UPDATE SET
                    jersey_number=excluded.jersey_number,
                    w=excluded.w,
                    l=excluded.l,
                    sv=excluded.sv,
                    g=excluded.g,
                    outs=excluded.outs,
                    ip_raw=excluded.ip_raw,
                    ab=excluded.ab,
                    h=excluded.h,
                    doubles=excluded.doubles,
                    triples=excluded.triples,
                    hr=excluded.hr,
                    bb=excluded.bb,
                    so=excluded.so,
                    r=excluded.r,
                    er=excluded.er,
                    site_opp_avg=excluded.site_opp_avg,
                    site_era=excluded.site_era;
                """,
                (
                    pt["team_id"],
                    pt["player_uid"],
                    pt["jersey_number"],
                    pt["w"],
                    pt["l"],
                    pt["sv"],
                    pt["g"],
                    pt["outs"],
                    pt["ip_raw"],
                    pt["ab"],
                    pt["h"],
                    pt["doubles"],
                    pt["triples"],
                    pt["hr"],
                    pt["bb"],
                    pt["so"],
                    pt["r"],
                    pt["er"],
                    pt["site_opp_avg"],
                    pt["site_era"],
                ),
            )


def parse_all(
    db_path: Path | str = DEFAULT_DB_PATH,
    csv_path: Path | str = DEFAULT_CSV_PATH,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> None:
    """批次解析所有種子快取頁面入庫。"""
    init_db(db_path)
    conn = get_db_connection(db_path)
    seeds = load_seeds(csv_path)

    print(f"[*] 開始解析 {len(seeds)} 隊快取資料並寫入 SQLite: {db_path}...")
    try:
        for idx, seed in enumerate(seeds, start=1):
            parse_and_store_team(seed=seed, conn=conn, cache_dir=cache_dir)
            if idx % 10 == 0 or idx == len(seeds):
                print(f"  - 進度: [{idx}/{len(seeds)}] 隊解析完成")
    finally:
        conn.close()
    print("[+] 全部 HTML 解析與入庫作業順利完成！")


def main():
    parser = argparse.ArgumentParser(description="台中小海盜 HTML 本地快取解析入庫器")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH), help="SQLite 資料庫路徑")
    args = parser.parse_args()

    parse_all(db_path=args.db)


if __name__ == "__main__":
    main()
