"""台中小海盜棒球數據戰情與成長查詢看板 (src/app.py)。

遵守規範：
- 使用 Streamlit + Plotly 連接 data/pirates.db (唯讀模式)
- 全域左側邊欄提供層級 (U8/U10/U12/U15)、分隊群組、年度、季節與賽制篩選
- 支援 7 局制 (少棒) 與 9 局制防禦率切換
- 嚴格落實球員唯一識別 (player_uid)，精準區分同名選手 (如 蔡〇宇_2015-11 vs 蔡〇宇_2017-06)
"""

import datetime
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 支援直接執行腳本時能匯入根目錄模組
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DB_FILE = PROJECT_ROOT / "data" / "pirates.db"

# 嘗試匯入爬蟲更新管線（若在雲端環境缺少爬蟲相依套件時平滑降級）
try:
    from run_pipeline import run_pipeline
    CAN_SYNC = True
except ImportError:
    run_pipeline = None
    CAN_SYNC = False

st.set_page_config(
    page_title="台中小海盜棒球戰情與數據庫",
    page_icon="🏴‍☠️",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_db():
    if not DB_FILE.exists():
        st.error(f"找不到資料庫檔案：{DB_FILE}，請確認 data/pirates.db 是否已提交至儲存庫。")
        st.stop()
    # 使用唯讀模式 (mode=ro) 開啟 SQLite，保證看板純讀取，不進行任何寫入操作
    db_uri = f"file:{DB_FILE.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


conn = get_db()

# ============================================================
# 全域側邊欄篩選器 (Sidebar Filters)
# ============================================================
st.sidebar.title("🏴‍☠️ 台中小海盜數據庫")
st.sidebar.caption("台中就是棒社區棒球聯賽 2024–2026")

# 1. 年齡層級篩選 (U8 / U10 / U12 / U15)
all_age_groups = ["U8", "U10", "U12", "U15"]
selected_age_groups = st.sidebar.multiselect(
    "🏆 年齡層級 (Age Group)",
    options=all_age_groups,
    default=all_age_groups,
    help="包含 U8、U10、U12 少棒組以及 U15 青少棒組",
)

# 2. 分隊群組篩選
all_team_groups = ["海盜本隊", "白隊", "黑隊", "U15海盜"]
selected_team_groups = st.sidebar.multiselect(
    "⚓ 分隊群組 (Team Group)",
    options=all_team_groups,
    default=all_team_groups,
    help="包含台中小海盜本隊、黑/白分隊及 U15 台中海盜",
)

# 3. 年度篩選
all_years = [2024, 2025, 2026]
selected_years = st.sidebar.multiselect(
    "📅 年度 (Year)",
    options=all_years,
    default=all_years,
)

# 4. 賽季篩選
all_seasons = ["春季", "秋季", "其他"]
selected_seasons = st.sidebar.multiselect(
    "🍂 賽季 (Season)",
    options=all_seasons,
    default=all_seasons,
)

# 5. 賽制篩選
all_tourneys = ["例行賽", "季後賽", "台灣大賽"]
selected_tourneys = st.sidebar.multiselect(
    "⚾ 賽制 (Tournament)",
    options=all_tourneys,
    default=all_tourneys,
)

# 6. 防禦率計算基準 (7 局制少棒 vs 9 局制標準)
era_innings = st.sidebar.radio(
    "📐 ERA 防禦率換算基準",
    options=[7, 9],
    index=0,
    format_func=lambda x: f"{x} 局制 ({'少棒比賽標準' if x==7 else '職業/網站預設'})",
    help="少棒正式賽制一般為 6 或 7 局，本看板提供 7 局與 9 局換算標準切換",
)

st.sidebar.divider()

# 資料庫最後更新時間與手動同步按鈕
def get_last_updated_time() -> str:
    try:
        cur = conn.cursor()
        cur.execute("SELECT max(last_fetched_at) FROM teams")
        row = cur.fetchone()
        if row and row[0]:
            dt = datetime.datetime.fromisoformat(row[0]).astimezone()
            return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return "未知"

last_update_str = get_last_updated_time()
st.sidebar.info(f"🕒 **最後更新時間**\n\n{last_update_str}")

# 若在本機環境且有完整爬蟲環境，提供即時重爬按鈕；雲端環境則引導使用一鍵腳本
if CAN_SYNC:
    if st.sidebar.button("🔄 本機同步最新戰績 (2026)", use_container_width=True, help="重新爬取 2026 年最新網頁快取、解析入庫並刷新看板"):
        with st.spinner("正在安全連線下載最新賽事快取並重新入庫，請稍候..."):
            try:
                success = run_pipeline(refresh_year=2026)
                if success:
                    st.sidebar.success("✅ 資料庫更新完成！")
                    st.cache_resource.clear()
                    st.rerun()
                else:
                    st.sidebar.error("❌ 更新失敗，請檢查資料管線記錄。")
            except Exception as e:
                st.sidebar.error(f"❌ 更新發生錯誤: {e}")
else:
    st.sidebar.caption("💡 雲端看板為唯讀展示，若需更新數據請在本機雙擊 `update_all.bat` 自動推送。")

st.sidebar.markdown(
    """
    **專案規範遵循：**
    - ✅ 嚴格依 `player_uid` 歸戶
    - ✅ 出局數整數入庫 (`outs`)
    - ✅ 本地快取禮貌爬蟲
    """
)

# 防呆檢查：若篩選為空
if not (selected_age_groups and selected_team_groups and selected_years and selected_seasons and selected_tourneys):
    st.warning("⚠️ 請在左側邊欄至少各勾選一項篩選條件！")
    st.stop()


# 取得符合條件的 team_id 清單
def get_filtered_team_ids() -> List[int]:
    q = f"""
    SELECT t.team_id
    FROM teams t
    JOIN leagues l ON t.league_id = l.league_id
    WHERE l.age_group IN ({','.join('?' for _ in selected_age_groups)})
      AND t.team_group IN ({','.join('?' for _ in selected_team_groups)})
      AND l.year IN ({','.join('?' for _ in selected_years)})
      AND l.season IN ({','.join('?' for _ in selected_seasons)})
      AND l.tournament_type IN ({','.join('?' for _ in selected_tourneys)})
    """
    params = selected_age_groups + selected_team_groups + selected_years + selected_seasons + selected_tourneys
    cur = conn.cursor()
    cur.execute(q, params)
    return [r[0] for r in cur.fetchall()]


filtered_team_ids = get_filtered_team_ids()

if not filtered_team_ids:
    st.info("ℹ️ 在目前選定的篩選條件下無符合的球隊資料，請放寬側邊欄條件。")
    st.stop()

# ============================================================
# 看板四大核心頁籤 (Main Tabs)
# ============================================================
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📊 分隊戰情總覽",
        "🏆 投打排行榜",
        "👤 球員跨屆成長檔案",
        "⚔️ 賽程戰果與對手分析",
    ]
)

# ------------------------------------------------------------
# 頁面 1: 分隊戰情總覽 (Team Overview)
# ------------------------------------------------------------
with tab1:
    st.header("📊 分隊戰情與總體戰績總覽")

    # 查詢團隊比賽勝負與得失分
    team_placeholders = ",".join("?" for _ in filtered_team_ids)
    matches_df = pd.read_sql_query(
        f"""
        SELECT m.team_id, m.away_team, m.home_team, m.away_score, m.home_score,
               t.team_name, t.team_group, l.year, l.season, l.age_group, l.league_title
        FROM matches m
        JOIN teams t ON m.team_id = t.team_id
        JOIN leagues l ON m.league_id = l.league_id
        WHERE m.team_id IN ({team_placeholders})
          AND m.away_score IS NOT NULL AND m.home_score IS NOT NULL
        """,
        conn,
        params=filtered_team_ids,
    )

    total_matches = len(matches_df)
    wins = 0
    losses = 0
    ties = 0
    runs_scored = 0
    runs_allowed = 0

    for _, row in matches_df.iterrows():
        away_s = row["away_score"]
        home_s = row["home_score"]
        is_away_pirate = "海盜" in row["away_team"] or row["away_team"] == row["team_name"]

        if is_away_pirate:
            my_s = away_s
            opp_s = home_s
        else:
            my_s = home_s
            opp_s = away_s

        runs_scored += my_s
        runs_allowed += opp_s

        if my_s > opp_s:
            wins += 1
        elif my_s < opp_s:
            losses += 1
        else:
            ties += 1

    win_rate = (wins / total_matches) if total_matches > 0 else 0.0

    # 團隊打擊與投球聚合
    bat_agg = pd.read_sql_query(
        f"""
        SELECT SUM(b.pa) as pa, SUM(b.ab) as ab, SUM(b.h) as h,
               SUM(b.doubles) as doubles, SUM(b.triples) as triples, SUM(b.hr) as hr,
               SUM(b.bb) as bb, SUM(b.so) as so, SUM(b.r) as r, SUM(b.rbi) as rbi
        FROM team_batting_stats b
        WHERE b.team_id IN ({team_placeholders})
        """,
        conn,
        params=filtered_team_ids,
    ).iloc[0]

    pitch_agg = pd.read_sql_query(
        f"""
        SELECT SUM(pt.outs) as total_outs, SUM(pt.er) as er,
               SUM(pt.h) as h, SUM(pt.bb) as bb, SUM(pt.so) as so, SUM(pt.r) as r
        FROM team_pitching_stats pt
        WHERE pt.team_id IN ({team_placeholders})
        """,
        conn,
        params=filtered_team_ids,
    ).iloc[0]

    # 計算三圍與防禦率
    team_ab = bat_agg["ab"] or 0
    team_h = bat_agg["h"] or 0
    team_bb = bat_agg["bb"] or 0
    team_2b = bat_agg["doubles"] or 0
    team_3b = bat_agg["triples"] or 0
    team_hr = bat_agg["hr"] or 0
    team_tb = team_h + team_2b + 2 * team_3b + 3 * team_hr

    team_avg = (team_h / team_ab) if team_ab > 0 else 0.0
    team_obp = ((team_h + team_bb) / (team_ab + team_bb)) if (team_ab + team_bb) > 0 else 0.0
    team_slg = (team_tb / team_ab) if team_ab > 0 else 0.0
    team_ops = team_obp + team_slg

    team_outs = pitch_agg["total_outs"] or 0
    team_er = pitch_agg["er"] or 0
    team_ph = pitch_agg["h"] or 0
    team_pbb = pitch_agg["bb"] or 0
    team_pso = pitch_agg["so"] or 0

    team_era = ((team_er * (21.0 if era_innings == 7 else 27.0)) / team_outs) if team_outs > 0 else 0.0
    team_whip = (((team_ph + team_pbb) * 3.0) / team_outs) if team_outs > 0 else 0.0
    team_k7 = ((team_pso * 21.0) / team_outs) if team_outs > 0 else 0.0

    # KPI 摘要展示
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric("出賽戰績 (W-L-T)", f"{wins}勝 {losses}敗 {ties}和", f"勝率: {win_rate:.3f}")
    kpi2.metric("得失分差", f"{runs_scored} - {runs_allowed}", f"淨勝分: {runs_scored - runs_allowed:+d}")
    kpi3.metric("場均得 / 失分", f"{runs_scored/max(1, total_matches):.1f} / {runs_allowed/max(1, total_matches):.1f}")
    kpi4.metric("團隊打擊三圍 (AVG/OBP/SLG)", f"{team_avg:.3f} / {team_obp:.3f} / {team_slg:.3f}", f"OPS: {team_ops:.3f}")
    kpi5.metric(f"團隊 ERA ({era_innings}局制) / WHIP", f"{team_era:.2f}", f"WHIP: {team_whip:.2f} | K/7: {team_k7:.2f}")

    st.markdown("---")

    # 各分隊戰績詳細表格
    st.subheader("📋 各聯賽參賽球隊戰績明細")
    teams_summary_df = pd.read_sql_query(
        f"""
        SELECT t.team_id, t.team_name, t.team_group, l.year, l.season, l.age_group, l.division,
               l.tournament_type, l.league_title, t.leader, t.head_coach
        FROM teams t
        JOIN leagues l ON t.league_id = l.league_id
        WHERE t.team_id IN ({team_placeholders})
        ORDER BY l.year DESC, l.age_group, t.team_group
        """,
        conn,
        params=filtered_team_ids,
    )

    # 組合每隊數據
    table_rows = []
    for _, t_row in teams_summary_df.iterrows():
        tid = t_row["team_id"]
        t_matches = matches_df[matches_df["team_id"] == tid]
        t_wins = 0
        t_losses = 0
        t_ties = 0
        t_runs = 0
        t_ra = 0
        for _, m in t_matches.iterrows():
            is_away = "海盜" in m["away_team"] or m["away_team"] == t_row["team_name"]
            my = m["away_score"] if is_away else m["home_score"]
            opp = m["home_score"] if is_away else m["away_score"]
            t_runs += my
            t_ra += opp
            if my > opp:
                t_wins += 1
            elif my < opp:
                t_losses += 1
            else:
                t_ties += 1

        table_rows.append(
            {
                "年度": t_row["year"],
                "賽季": t_row["season"],
                "層級": t_row["age_group"],
                "組別": t_row["division"],
                "群組": t_row["team_group"],
                "球隊名稱": t_row["team_name"],
                "賽事名稱": t_row["league_title"],
                "出賽": len(t_matches),
                "勝": t_wins,
                "敗": t_losses,
                "和": t_ties,
                "勝率": f"{(t_wins/len(t_matches)):.3f}" if len(t_matches) > 0 else "-",
                "得分": t_runs,
                "失分": t_ra,
                "總教練": t_row["head_coach"] or "-",
            }
        )

    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)


# ------------------------------------------------------------
# 頁面 2: 投打排行榜 (Leaderboards)
# ------------------------------------------------------------
with tab2:
    st.header("🏆 投打攻守排行榜")

    mode = st.radio(
        "選擇統計視角",
        options=["符合條件的跨季生涯合併", "單季分隊成績"],
        horizontal=True,
    )

    tab_bat, tab_pitch = st.tabs(["⚾ 打者排行榜", "🎯 投手排行榜"])

    # --- 打者排行榜 ---
    with tab_bat:
        c1, c2 = st.columns([1, 3])
        with c1:
            min_pa = st.slider("最低打席門檻 (Min PA)", min_value=0, max_value=50, value=5, step=1)

        if mode == "符合條件的跨季生涯合併":
            bat_sql = f"""
            SELECT
                p.player_uid,
                p.masked_name AS 姓名,
                p.birth_ym AS 生日,
                GROUP_CONCAT(DISTINCT l.age_group) AS 層級,
                COUNT(DISTINCT b.team_id) AS 出賽隊數,
                SUM(b.g) AS G,
                SUM(b.pa) AS PA,
                SUM(b.ab) AS AB,
                SUM(b.h) AS H,
                SUM(b.doubles) AS 二壘打,
                SUM(b.triples) AS 三壘打,
                SUM(b.hr) AS 全壘打,
                SUM(b.rbi) AS 打點,
                SUM(b.r) AS 得分,
                SUM(b.bb) AS 四死,
                SUM(b.so) AS 三振,
                SUM(COALESCE(b.sb_top10, 0)) AS 盜壘,
                ROUND(CAST(SUM(b.h) AS REAL) / MAX(1, SUM(b.ab)), 3) AS AVG,
                ROUND(CAST(SUM(b.h + b.bb) AS REAL) / MAX(1, SUM(b.ab + b.bb)), 3) AS OBP,
                ROUND(CAST(SUM(b.h + b.doubles + 2 * b.triples + 3 * b.hr) AS REAL) / MAX(1, SUM(b.ab)), 3) AS SLG,
                ROUND(
                    (CAST(SUM(b.h + b.bb) AS REAL) / MAX(1, SUM(b.ab + b.bb))) +
                    (CAST(SUM(b.h + b.doubles + 2 * b.triples + 3 * b.hr) AS REAL) / MAX(1, SUM(b.ab))), 3
                ) AS OPS
            FROM players p
            JOIN team_batting_stats b ON p.player_uid = b.player_uid
            JOIN teams t ON b.team_id = t.team_id
            JOIN leagues l ON t.league_id = l.league_id
            WHERE b.team_id IN ({team_placeholders})
            GROUP BY p.player_uid
            HAVING SUM(b.pa) >= ?
            ORDER BY OPS DESC, AVG DESC, H DESC;
            """
            bat_df = pd.read_sql_query(bat_sql, conn, params=filtered_team_ids + [min_pa])
        else:
            bat_sql = f"""
            SELECT
                p.player_uid,
                p.masked_name AS 姓名,
                p.birth_ym AS 生日,
                b.jersey_number AS 背號,
                t.team_name AS 球隊,
                l.year AS 年度,
                l.season AS 賽季,
                l.age_group AS 層級,
                b.g AS G,
                b.pa AS PA,
                b.ab AS AB,
                b.h AS H,
                b.doubles AS 二壘打,
                b.triples AS 三壘打,
                b.hr AS 全壘打,
                b.rbi AS 打點,
                b.r AS 得分,
                b.bb AS 四死,
                b.so AS 三振,
                COALESCE(b.sb_top10, 0) AS 盜壘,
                ROUND(CAST(b.h AS REAL) / MAX(1, b.ab), 3) AS AVG,
                ROUND(CAST(b.h + b.bb AS REAL) / MAX(1, b.ab + b.bb), 3) AS OBP,
                ROUND(CAST(b.h + b.doubles + 2 * b.triples + 3 * b.hr AS REAL) / MAX(1, b.ab), 3) AS SLG,
                ROUND(
                    (CAST(b.h + b.bb AS REAL) / MAX(1, b.ab + b.bb)) +
                    (CAST(b.h + b.doubles + 2 * b.triples + 3 * b.hr AS REAL) / MAX(1, b.ab)), 3
                ) AS OPS
            FROM team_batting_stats b
            JOIN players p ON b.player_uid = p.player_uid
            JOIN teams t ON b.team_id = t.team_id
            JOIN leagues l ON t.league_id = l.league_id
            WHERE b.team_id IN ({team_placeholders})
              AND b.pa >= ?
            ORDER BY OPS DESC, AVG DESC, H DESC;
            """
            bat_df = pd.read_sql_query(bat_sql, conn, params=filtered_team_ids + [min_pa])

        st.caption(f"共計找到 {len(bat_df)} 位符合門檻之打者")
        st.dataframe(bat_df, use_container_width=True, hide_index=True)

        csv_bat = bat_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "📥 下載打者排行榜 CSV",
            data=csv_bat,
            file_name="pirates_batting_leaderboard.csv",
            mime="text/csv",
        )

    # --- 投手排行榜 ---
    with tab_pitch:
        c1, c2 = st.columns([1, 3])
        with c1:
            min_ip = st.slider("最低局數門檻 (Min IP)", min_value=0, max_value=30, value=3, step=1)
        min_outs = min_ip * 3

        era_factor = 21.0 if era_innings == 7 else 27.0

        if mode == "符合條件的跨季生涯合併":
            pitch_sql = f"""
            SELECT
                p.player_uid,
                p.masked_name AS 姓名,
                p.birth_ym AS 生日,
                GROUP_CONCAT(DISTINCT l.age_group) AS 層級,
                SUM(pt.w) AS 勝,
                SUM(pt.l) AS 敗,
                SUM(pt.sv) AS 救援,
                SUM(pt.g) AS G,
                printf('%d.%d', SUM(pt.outs)/3, SUM(pt.outs)%3) AS IP,
                SUM(pt.outs) AS 出局數,
                SUM(pt.h) AS 被安,
                SUM(pt.r) AS 失分,
                SUM(pt.er) AS 責失,
                SUM(pt.bb) AS 保送,
                SUM(pt.so) AS 奪三振,
                SUM(pt.hr) AS 被全壘打,
                CASE WHEN SUM(pt.outs) > 0
                     THEN ROUND((SUM(pt.er) * {era_factor}) / SUM(pt.outs), 2)
                     ELSE NULL END AS ERA,
                CASE WHEN SUM(pt.outs) > 0
                     THEN ROUND(((SUM(pt.h) + SUM(pt.bb)) * 3.0) / SUM(pt.outs), 2)
                     ELSE NULL END AS WHIP,
                CASE WHEN SUM(pt.outs) > 0
                     THEN ROUND((SUM(pt.so) * 21.0) / SUM(pt.outs), 2)
                     ELSE NULL END AS 'K/7'
            FROM players p
            JOIN team_pitching_stats pt ON p.player_uid = pt.player_uid
            JOIN teams t ON pt.team_id = t.team_id
            JOIN leagues l ON t.league_id = l.league_id
            WHERE pt.team_id IN ({team_placeholders})
              AND p.player_uid != 'coach_pitch_888'
            GROUP BY p.player_uid
            HAVING SUM(pt.outs) >= ?
            ORDER BY ERA ASC, 出局數 DESC;
            """
            pitch_df = pd.read_sql_query(pitch_sql, conn, params=filtered_team_ids + [min_outs])
        else:
            pitch_sql = f"""
            SELECT
                p.player_uid,
                p.masked_name AS 姓名,
                p.birth_ym AS 生日,
                pt.jersey_number AS 背號,
                t.team_name AS 球隊,
                l.year AS 年度,
                l.season AS 賽季,
                l.age_group AS 層級,
                pt.w AS 勝,
                pt.l AS 敗,
                pt.sv AS 救援,
                pt.g AS G,
                printf('%d.%d', pt.outs/3, pt.outs%3) AS IP,
                pt.outs AS 出局數,
                pt.h AS 被安,
                pt.r AS 失分,
                pt.er AS 責失,
                pt.bb AS 保送,
                pt.so AS 奪三振,
                pt.hr AS 被全壘打,
                CASE WHEN pt.outs > 0
                     THEN ROUND((pt.er * {era_factor}) / pt.outs, 2)
                     ELSE NULL END AS ERA,
                CASE WHEN pt.outs > 0
                     THEN ROUND(((pt.h + pt.bb) * 3.0) / pt.outs, 2)
                     ELSE NULL END AS WHIP,
                CASE WHEN pt.outs > 0
                     THEN ROUND((pt.so * 21.0) / pt.outs, 2)
                     ELSE NULL END AS 'K/7'
            FROM team_pitching_stats pt
            JOIN players p ON pt.player_uid = p.player_uid
            JOIN teams t ON pt.team_id = t.team_id
            JOIN leagues l ON t.league_id = l.league_id
            WHERE pt.team_id IN ({team_placeholders})
              AND p.player_uid != 'coach_pitch_888'
              AND pt.outs >= ?
            ORDER BY ERA ASC, pt.outs DESC;
            """
            pitch_df = pd.read_sql_query(pitch_sql, conn, params=filtered_team_ids + [min_outs])

        st.caption(f"共計找到 {len(pitch_df)} 位符合門檻之投手 (已排除教練拋打)")
        if not pitch_df.empty:
            pitch_df["IP"] = pitch_df["出局數"].apply(lambda o: round((o // 3) + (o % 3) * 0.1, 1))
        st.dataframe(
            pitch_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "IP": st.column_config.NumberColumn(
                    "IP",
                    help="投球局數 (小數點後為出局數，如 10.1 代表 10 局又 1 出局)",
                    format="%.1f",
                )
            },
        )

        csv_pitch = pitch_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "📥 下載投手排行榜 CSV",
            data=csv_pitch,
            file_name="pirates_pitching_leaderboard.csv",
            mime="text/csv",
        )


# ------------------------------------------------------------
# 頁面 3: 球員跨屆成長檔案 (Player Profile)
# ------------------------------------------------------------
with tab3:
    st.header("👤 球員跨屆成長檔案（Player Profile）")

    # 取得所有球員名單並提供搜尋
    players_query = """
    SELECT
        p.player_uid,
        p.masked_name,
        p.birth_ym,
        GROUP_CONCAT(DISTINCT l.age_group) AS age_groups,
        GROUP_CONCAT(DISTINCT t.team_name) AS team_names,
        COUNT(DISTINCT t.team_id) AS total_teams
    FROM players p
    JOIN team_rosters r ON p.player_uid = r.player_uid
    JOIN teams t ON r.team_id = t.team_id
    JOIN leagues l ON t.league_id = l.league_id
    WHERE p.player_uid != 'coach_pitch_888'
    GROUP BY p.player_uid
    ORDER BY p.masked_name, p.birth_ym;
    """
    all_players_df = pd.read_sql_query(players_query, conn)

    # 建立清楚的下拉標籤
    player_options = {}
    for _, p_row in all_players_df.iterrows():
        b_str = f" (生日: {p_row['birth_ym']})" if p_row["birth_ym"] else ""
        label = f"{p_row['masked_name']}{b_str} ｜ 層級: {p_row['age_groups']} ({p_row['team_names']})"
        player_options[p_row["player_uid"]] = label

    # 預設選中 蔡〇宇_2015-11 供驗收
    default_uid = "蔡〇宇_2015-11" if "蔡〇宇_2015-11" in player_options else list(player_options.keys())[0]

    selected_uid = st.selectbox(
        "🔍 請輸入姓名或背號搜尋球員（支援精準區分同名選手）：",
        options=list(player_options.keys()),
        index=list(player_options.keys()).index(default_uid),
        format_func=lambda x: player_options[x],
    )

    if selected_uid:
        p_info = all_players_df[all_players_df["player_uid"] == selected_uid].iloc[0]

        st.subheader(f"🌟 {p_info['masked_name']} 的棒球履歷與成長軌跡")
        st.markdown(
            f"**全域身分 ID (`player_uid`)**: `{p_info['player_uid']}` &nbsp;|&nbsp; "
            f"**出生年月**: `{p_info['birth_ym'] or '未登錄'}` &nbsp;|&nbsp; "
            f"**曾參與層級**: `{p_info['age_groups']}` &nbsp;|&nbsp; "
            f"**歷經球隊數**: `{p_info['total_teams']} 隊`"
        )

        # 取得該球員打擊歷屆出賽
        p_bat_df = pd.read_sql_query(
            """
            SELECT
                l.year AS 年度,
                l.season AS 賽季,
                l.age_group AS 層級,
                t.team_name AS 球隊,
                b.jersey_number AS 背號,
                b.g AS G,
                b.pa AS PA,
                b.ab AS AB,
                b.h AS H,
                b.doubles AS 二壘打,
                b.triples AS 三壘打,
                b.hr AS 全壘打,
                b.rbi AS 打點,
                b.r AS 得分,
                b.bb AS 保送,
                b.so AS 三振,
                ROUND(CAST(b.h AS REAL) / MAX(1, b.ab), 3) AS AVG,
                ROUND(CAST(b.h + b.bb AS REAL) / MAX(1, b.ab + b.bb), 3) AS OBP,
                ROUND(CAST(b.h + b.doubles + 2 * b.triples + 3 * b.hr AS REAL) / MAX(1, b.ab), 3) AS SLG,
                ROUND(
                    (CAST(b.h + b.bb AS REAL) / MAX(1, b.ab + b.bb)) +
                    (CAST(b.h + b.doubles + 2 * b.triples + 3 * b.hr AS REAL) / MAX(1, b.ab)), 3
                ) AS OPS
            FROM team_batting_stats b
            JOIN teams t ON b.team_id = t.team_id
            JOIN leagues l ON t.league_id = l.league_id
            WHERE b.player_uid = ?
            ORDER BY l.year ASC, l.season ASC, l.age_group ASC;
            """,
            conn,
            params=[selected_uid],
        )

        # 取得該球員投球歷屆出賽
        era_f = 21.0 if era_innings == 7 else 27.0
        p_pitch_df = pd.read_sql_query(
            f"""
            SELECT
                l.year AS 年度,
                l.season AS 賽季,
                l.age_group AS 層級,
                t.team_name AS 球隊,
                pt.jersey_number AS 背號,
                pt.w AS 勝,
                pt.l AS 敗,
                pt.sv AS 救援,
                pt.g AS G,
                printf('%d.%d', pt.outs/3, pt.outs%3) AS IP,
                pt.outs AS 出局數,
                pt.h AS 被安,
                pt.r AS 失分,
                pt.er AS 責失,
                pt.bb AS 保送,
                pt.so AS 奪三振,
                CASE WHEN pt.outs > 0
                     THEN ROUND((pt.er * {era_f}) / pt.outs, 2)
                     ELSE NULL END AS ERA,
                CASE WHEN pt.outs > 0
                     THEN ROUND(((pt.h + pt.bb) * 3.0) / pt.outs, 2)
                     ELSE NULL END AS WHIP,
                CASE WHEN pt.outs > 0
                     THEN ROUND((pt.so * 21.0) / pt.outs, 2)
                     ELSE NULL END AS 'K/7'
            FROM team_pitching_stats pt
            JOIN teams t ON pt.team_id = t.team_id
            JOIN leagues l ON t.league_id = l.league_id
            WHERE pt.player_uid = ?
            ORDER BY l.year ASC, l.season ASC, l.age_group ASC;
            """,
            conn,
            params=[selected_uid],
        )

        st.markdown("### 🏏 歷屆打擊明細紀錄")
        if not p_bat_df.empty:
            st.dataframe(p_bat_df, use_container_width=True, hide_index=True)

            # 打擊成長圖
            p_bat_df["賽季標籤"] = p_bat_df["年度"].astype(str) + " " + p_bat_df["賽季"] + " " + p_bat_df["層級"]
            fig_bat = go.Figure()
            fig_bat.add_trace(go.Scatter(x=p_bat_df["賽季標籤"], y=p_bat_df["AVG"], mode="lines+markers+text", name="打擊率 (AVG)", text=p_bat_df["AVG"], textposition="top center"))
            fig_bat.add_trace(go.Scatter(x=p_bat_df["賽季標籤"], y=p_bat_df["OBP"], mode="lines+markers", name="上壘率 (OBP)"))
            fig_bat.add_trace(go.Scatter(x=p_bat_df["賽季標籤"], y=p_bat_df["SLG"], mode="lines+markers", name="長打率 (SLG)"))
            fig_bat.add_trace(go.Scatter(x=p_bat_df["賽季標籤"], y=p_bat_df["OPS"], mode="lines+markers+text", name="整體攻擊 (OPS)", text=p_bat_df["OPS"], textposition="bottom center", line=dict(dash="dash", width=3)))
            fig_bat.update_layout(title=f"{p_info['masked_name']} 歷屆打擊指標成長趨勢", xaxis_title="參賽賽程", yaxis_title="比率數值", hovermode="x unified")
            st.plotly_chart(fig_bat, use_container_width=True)
        else:
            st.info("尚無打擊紀錄。")

        st.markdown("### ⚾ 歷屆投球明細紀錄")
        if not p_pitch_df.empty:
            p_pitch_df["IP"] = p_pitch_df["出局數"].apply(lambda o: round((o // 3) + (o % 3) * 0.1, 1))
            st.dataframe(
                p_pitch_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "IP": st.column_config.NumberColumn(
                        "IP",
                        help="投球局數 (小數點後為出局數，如 10.1 代表 10 局又 1 出局)",
                        format="%.1f",
                    )
                },
            )

            # 投球成長圖
            p_pitch_df["賽季標籤"] = p_pitch_df["年度"].astype(str) + " " + p_pitch_df["賽季"] + " " + p_pitch_df["層級"]
            fig_pitch = go.Figure()
            fig_pitch.add_trace(go.Scatter(x=p_pitch_df["賽季標籤"], y=p_pitch_df["ERA"], mode="lines+markers+text", name=f"防禦率 ERA ({era_innings}局制)", text=p_pitch_df["ERA"], textposition="top center"))
            fig_pitch.add_trace(go.Scatter(x=p_pitch_df["賽季標籤"], y=p_pitch_df["WHIP"], mode="lines+markers", name="每局被上壘率 (WHIP)"))
            fig_pitch.add_trace(go.Scatter(x=p_pitch_df["賽季標籤"], y=p_pitch_df["K/7"], mode="lines+markers", name="K/7 (7局三振率)"))
            fig_pitch.update_layout(title=f"{p_info['masked_name']} 歷屆投球防禦與三振表現", xaxis_title="參賽賽程", yaxis_title="比率數值", hovermode="x unified")
            st.plotly_chart(fig_pitch, use_container_width=True)
        else:
            st.info("尚無投球紀錄。")


# ------------------------------------------------------------
# 頁面 4: 賽程戰果與對手分析 (Match Analysis & Opponents)
# ------------------------------------------------------------
with tab4:
    st.header("⚔️ 賽程戰果與對戰對手深度分析")

    # 萃取所有對手名單
    opponents_df = pd.read_sql_query(
        f"""
        SELECT m.away_team, m.home_team
        FROM matches m
        WHERE m.team_id IN ({team_placeholders})
        """,
        conn,
        params=filtered_team_ids,
    )

    all_opps = set()
    for _, r in opponents_df.iterrows():
        for t_name in (r["away_team"], r["home_team"]):
            t_name = t_name.strip()
            if "海盜" not in t_name and t_name:
                all_opps.add(t_name)

    all_opps_sorted = sorted(list(all_opps))

    selected_opp = st.selectbox(
        "🎯 選擇對抗對手球隊（如：健行小牛、台中道奇等）：",
        options=["全部對手"] + all_opps_sorted,
    )

    # 查詢與該對手所有對戰比賽
    if selected_opp == "全部對手":
        opp_condition = ""
        opp_params = filtered_team_ids
    else:
        opp_condition = "AND (m.away_team = ? OR m.home_team = ?)"
        opp_params = filtered_team_ids + [selected_opp, selected_opp]

    opp_matches_sql = f"""
    SELECT
        m.id,
        m.match_date_iso AS 比賽日期,
        m.match_time AS 時間,
        l.year AS 年度,
        l.season AS 賽季,
        l.age_group AS 層級,
        t.team_name AS 海盜球隊,
        m.away_team AS 客隊,
        m.away_score AS 客得分,
        m.home_score AS 主得分,
        m.home_team AS 主隊,
        m.venue AS 場地,
        m.boxscore_url,
        m.pbp_url,
        m.summary_url
    FROM matches m
    JOIN teams t ON m.team_id = t.team_id
    JOIN leagues l ON m.league_id = l.league_id
    WHERE m.team_id IN ({team_placeholders})
      {opp_condition}
    ORDER BY m.match_date_iso DESC, m.match_time DESC;
    """
    m_list_df = pd.read_sql_query(opp_matches_sql, conn, params=opp_params)

    # 統計對戰勝負
    o_wins = 0
    o_losses = 0
    o_ties = 0
    o_rf = 0
    o_ra = 0
    display_rows = []

    for _, row in m_list_df.iterrows():
        away_s = row["客得分"]
        home_s = row["主得分"]
        is_away_p = "海盜" in row["客隊"]

        if pd.notna(away_s) and pd.notna(home_s):
            my_score = int(away_s) if is_away_p else int(home_s)
            opp_score = int(home_s) if is_away_p else int(away_s)
            o_rf += my_score
            o_ra += opp_score

            if my_score > opp_score:
                o_wins += 1
                res_tag = "🟢 勝"
            elif my_score < opp_score:
                o_losses += 1
                res_tag = "🔴 敗"
            else:
                o_ties += 1
                res_tag = "🟡 和"
            score_str = f"{row['客隊']} {int(away_s)} : {int(home_s)} {row['主隊']}"
        else:
            res_tag = "⏳ 未開賽"
            score_str = f"{row['客隊']} vs. {row['主隊']}"

        display_rows.append(
            {
                "日期": row["比賽日期"] or "-",
                "時間": row["時間"] or "-",
                "年度/賽季": f"{row['年度']} {row['賽季']}",
                "層級": row["層級"],
                "海盜球隊": row["海盜球隊"],
                "對戰比分": score_str,
                "戰果": res_tag,
                "場地": row["場地"] or "-",
                "攻守數據": row["boxscore_url"] if pd.notna(row["boxscore_url"]) else None,
                "文字紀錄": row["pbp_url"] if pd.notna(row["pbp_url"]) else None,
                "戰況表": row["summary_url"] if pd.notna(row["summary_url"]) else None,
            }
        )

    o_total = o_wins + o_losses + o_ties
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("對戰總場次", f"{o_total} 場", f"未開賽: {len(m_list_df) - o_total} 場")
    c2.metric("對戰戰績", f"{o_wins}勝 {o_losses}敗 {o_ties}和", f"勝率: {(o_wins/max(1, o_total)):.3f}")
    c3.metric("總得失分", f"{o_rf} - {o_ra}", f"淨勝分: {o_rf - o_ra:+d}")
    c4.metric("場均得失分", f"{o_rf/max(1, o_total):.1f} / {o_ra/max(1, o_total):.1f}")

    st.markdown("---")
    st.subheader(f"📋 對戰明細列表 ({selected_opp})")
    st.dataframe(
        pd.DataFrame(display_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "攻守數據": st.column_config.LinkColumn("攻守數據", display_text="📊 攻守數據"),
            "文字紀錄": st.column_config.LinkColumn("文字紀錄", display_text="📝 文字紀錄"),
            "戰況表": st.column_config.LinkColumn("戰況表", display_text="📋 戰況表"),
        },
    )
