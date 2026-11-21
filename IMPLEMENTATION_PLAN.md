# 台中小海盜棒球數據資料庫 — 實作規格書（Implementation Plan）

## 一、 已確認專案範圍與核心決策（Confirmed Scope）

1. **納入範圍（含 U15 台中海盜）**
   - 第一階段以 `data/海盜隊網頁標題.csv` 內的 **41 筆團隊聯賽頁** 為主（涵蓋 `台中小海盜`、`台中小海盜(白)`、`台中小海盜(白)A`、`台中小海盜(白)B`、`台中小海盜(黑)`，以及編號 37–41 的 **U15 `台中海盜`**）。
   - 查詢看板必須提供「年齡層級（U8 / U10 / U12 / U15）」與「分隊群組（本隊 / 白隊 / 黑隊 / U15海盜）」自由開關與複選篩選器。
2. **第一階段爬取邊界**
   - 僅爬取 CSV 中這 41 頁 `team_detail.php`（每頁請求間隔 `1.5 ~ 2.5` 秒），不進行全站聯賽探索。
   - 賽程表中的單場連結（`攻守數據` / `文字紀錄` / `戰況表`）先萃取並儲存於 `matches` 表，保留給第二階段擴充。
3. **跨隊／跨屆球員唯一歸戶規則**
   - 先檢查網頁姓名/表格是否帶有 `player_id` 超連結（提取為 `site_player_id`）。
   - 若頁面上無 `player_id`，一律使用 **`{masked_name}_{birth_ym}`**（例如 `蔡〇宇_2015-11` 與 `蔡〇宇_2017-06`）作為全域唯一鍵 `player_uid`。
   - 解析當隊「打者表現」與「投手表現」表時，`Player` 欄位格式為 `背號 姓名`（如 `66 蔡〇宇`），必須優先用 **`(jersey_number, masked_name)`** 對應回該隊名冊表取得 `player_uid`，避免同隊同名遮罩球員混淆。
4. **已知網頁勘查特性與防呆要求**
   - **URL 參數語意**：網址中的 `game_id` 實為「聯賽組別 ID」（如多個分隊共用 `game_id=430`、`364`、`365`），資料庫中映射為 `leagues.league_id`。
   - **全形字元**：打者表場次表頭為**全形 `Ｇ`**，投手表為**半形 `G`**，解析時需正規化表頭。
   - **賽程重複渲染**：每一頁「本次賽事賽程及結果」在 HTML DOM 中會重複出現多次（約 5 次），解析時**僅取第一個賽程表格容器**，並靠資料庫 `UNIQUE` 約束防止重複寫入。
   - **局數與 0 局計算**：頁面 `IP` 為兩位小數三分數（`.00` / `.33` / `.67`），入庫一律轉整數出局數 `outs = round(float(ip) * 3)`；存在 `IP = 0.00` 但 `ER > 0`（網站 ERA 顯示 `0.00`）的情況，所有合併與看板 ERA 一律由 `outs` 與 `er` 重新計算。
   - **空資料容錯**：如 `team_id=4046`（2026 秋季 U8 黑隊）尚未開賽，名冊、賽程與投打表格皆為空，需安全跳過並正常完成隊伍建檔。
   - **CSV 編碼**：`海盜隊網頁標題.csv` 含有 UTF-8 BOM，讀取時必須指定 `encoding="utf-8-sig"`。

---

## 二、 `data/pirates.db` SQLite Schema 設計

建立 `src/db.py` 時，每次建立 SQLite 連線皆須執行 `PRAGMA foreign_keys = ON;`，並初始化以下 7 張資料表與 2 個分析用 SQL Views：

```sql
PRAGMA foreign_keys = ON;

-- 1. 聯賽／賽事組別維度表（對應網址 game_id）
CREATE TABLE IF NOT EXISTS leagues (
    league_id       INTEGER PRIMARY KEY,         -- 原網址參數 game_id (如 302, 430, 467)
    league_title    TEXT NOT NULL,               -- 完整賽事名稱
    year            INTEGER NOT NULL,            -- 年份 (2024, 2025, 2026)
    season          TEXT NOT NULL,               -- '春季' | '秋季' | '其他'
    tournament_type TEXT NOT NULL,               -- '例行賽' | '季後賽' | '台灣大賽'
    age_group       TEXT NOT NULL,               -- 'U8' | 'U10' | 'U12' | 'U15'
    division        TEXT NOT NULL                -- '大聯盟' | '小聯盟' | '一般'
);

-- 2. 參賽球隊主表（對應 CSV 41 筆）
CREATE TABLE IF NOT EXISTS teams (
    team_id         INTEGER PRIMARY KEY,         -- 原網址參數 team_id
    league_id       INTEGER NOT NULL REFERENCES leagues(league_id),
    csv_row_no      INTEGER,                     -- CSV 原始編號 (1~41)
    team_name       TEXT NOT NULL,               -- 如 '台中小海盜(白)A', '台中海盜'
    team_group      TEXT NOT NULL,               -- '海盜本隊' | '白隊' | '黑隊' | 'U15海盜'
    leader          TEXT,                        -- 領隊
    head_coach      TEXT,                        -- 總教練
    manager         TEXT,                        -- 管理
    coaches         TEXT,                        -- 教練
    source_url      TEXT NOT NULL,               -- 移除 #team-section 後之網址
    last_fetched_at TEXT                         -- ISO8601 下載時間
);

-- 3. 選手跨屆唯一識別表
CREATE TABLE IF NOT EXISTS players (
    player_uid      TEXT PRIMARY KEY,            -- 優先 'id:{site_player_id}'，無則 '{masked_name}_{birth_ym}'
    site_player_id  INTEGER,                     -- 網站內部 player_id (若無超連結則為 NULL)
    masked_name     TEXT NOT NULL,               -- 遮罩姓名 (如 '蔡〇宇')
    birth_ym        TEXT,                        -- 出生年月 'YYYY-MM' (如 '2015-11')
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(masked_name, birth_ym)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_players_site_id
    ON players(site_player_id)
    WHERE site_player_id IS NOT NULL;

-- 4. 各聯賽球隊登錄名冊
CREATE TABLE IF NOT EXISTS team_rosters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id         INTEGER NOT NULL REFERENCES teams(team_id),
    player_uid      TEXT NOT NULL REFERENCES players(player_uid),
    jersey_number   TEXT,                        -- 文字型別保留前導零 (如 '01')
    position        TEXT,                        -- 登錄守位 (如 'P', 'C', 'IF', 'OF')
    UNIQUE(team_id, player_uid)
);

-- 5. 單一聯賽球隊打者表現
CREATE TABLE IF NOT EXISTS team_batting_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id         INTEGER NOT NULL REFERENCES teams(team_id),
    player_uid      TEXT NOT NULL REFERENCES players(player_uid),
    jersey_number   TEXT,
    g               INTEGER NOT NULL DEFAULT 0,  -- 對應表頭全形 'Ｇ'
    pa              INTEGER NOT NULL DEFAULT 0,
    ab              INTEGER NOT NULL DEFAULT 0,
    h               INTEGER NOT NULL DEFAULT 0,
    doubles         INTEGER NOT NULL DEFAULT 0,  -- 對應 '2B'
    triples         INTEGER NOT NULL DEFAULT 0,  -- 對應 '3B'
    hr              INTEGER NOT NULL DEFAULT 0,
    bb              INTEGER NOT NULL DEFAULT 0,
    so              INTEGER NOT NULL DEFAULT 0,
    rbi             INTEGER NOT NULL DEFAULT 0,
    r               INTEGER NOT NULL DEFAULT 0,
    sb_top10        INTEGER,                     -- 頁尾 Top 10 - Batting 補充盜壘數 (非前十為 NULL)
    site_obp        REAL,                        -- 網站原始顯示 OBP (供驗證對照)
    site_slg        REAL,                        -- 網站原始顯示 SLG (供驗證對照)
    site_avg        REAL,                        -- 網站原始顯示 AVG (供驗證對照)
    UNIQUE(team_id, player_uid)
);

-- 6. 單一聯賽球隊投手表現
CREATE TABLE IF NOT EXISTS team_pitching_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id         INTEGER NOT NULL REFERENCES teams(team_id),
    player_uid      TEXT NOT NULL REFERENCES players(player_uid),
    jersey_number   TEXT,
    w               INTEGER NOT NULL DEFAULT 0,
    l               INTEGER NOT NULL DEFAULT 0,
    sv              INTEGER NOT NULL DEFAULT 0,
    g               INTEGER NOT NULL DEFAULT 0,  -- 對應表頭半形 'G'
    outs            INTEGER NOT NULL DEFAULT 0,  -- round(float(ip_raw) * 3)
    ip_raw          TEXT,                        -- 保留原始字串 (如 '18.67')
    ab              INTEGER NOT NULL DEFAULT 0,
    h               INTEGER NOT NULL DEFAULT 0,
    doubles         INTEGER NOT NULL DEFAULT 0,
    triples         INTEGER NOT NULL DEFAULT 0,
    hr              INTEGER NOT NULL DEFAULT 0,
    bb              INTEGER NOT NULL DEFAULT 0,
    so              INTEGER NOT NULL DEFAULT 0,
    r               INTEGER NOT NULL DEFAULT 0,
    er              INTEGER NOT NULL DEFAULT 0,
    site_opp_avg    REAL,                        -- 網站原始顯示被打擊率 (AVG)
    site_era        REAL,                        -- 網站原始顯示 ERA
    UNIQUE(team_id, player_uid)
);

-- 7. 本次賽事賽程及結果
CREATE TABLE IF NOT EXISTS matches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id         INTEGER NOT NULL REFERENCES teams(team_id),
    league_id       INTEGER NOT NULL REFERENCES leagues(league_id),
    match_date      TEXT,                        -- 原始日期 (如 '03/15')
    match_date_iso  TEXT,                        -- 推導日期 (如 '2026-03-15')
    match_time      TEXT,                        -- 如 '08:00'
    away_team       TEXT NOT NULL,
    home_team       TEXT NOT NULL,
    away_score      INTEGER,                     -- 未開賽顯示 ':' 時為 NULL
    home_score      INTEGER,                     -- 未開賽顯示 ':' 時為 NULL
    venue           TEXT,                        -- 場地
    boxscore_url    TEXT,                        -- '攻守數據' 連結 (預留 Phase 2)
    pbp_url         TEXT,                        -- '文字紀錄' 連結
    summary_url     TEXT,                        -- '戰況表' 連結
    UNIQUE(team_id, match_date, match_time, away_team, home_team)
);

-- ============================================================
-- 分析用 Views（支援跨屆動態重算率值，不受單頁四捨五入影響）
-- ============================================================

-- 跨季球員打擊生涯總表 View
CREATE VIEW IF NOT EXISTS v_player_career_batting AS
SELECT
    p.player_uid,
    p.masked_name,
    p.birth_ym,
    COUNT(DISTINCT b.team_id) AS seasons_played,
    GROUP_CONCAT(DISTINCT l.age_group) AS age_groups,
    SUM(b.g) AS g,
    SUM(b.pa) AS pa,
    SUM(b.ab) AS ab,
    SUM(b.h) AS h,
    SUM(b.doubles) AS doubles,
    SUM(b.triples) AS triples,
    SUM(b.hr) AS hr,
    SUM(b.bb) AS bb,
    SUM(b.so) AS so,
    SUM(b.rbi) AS rbi,
    SUM(b.r) AS r,
    SUM(b.h + b.doubles + 2 * b.triples + 3 * b.hr) AS total_bases,
    CASE WHEN SUM(b.ab) > 0
         THEN ROUND(CAST(SUM(b.h) AS REAL) / SUM(b.ab), 3)
         ELSE 0.0 END AS calc_avg,
    CASE WHEN SUM(b.ab + b.bb) > 0
         THEN ROUND(CAST(SUM(b.h + b.bb) AS REAL) / SUM(b.ab + b.bb), 3)
         ELSE 0.0 END AS calc_obp,
    CASE WHEN SUM(b.ab) > 0
         THEN ROUND(CAST(SUM(b.h + b.doubles + 2 * b.triples + 3 * b.hr) AS REAL) / SUM(b.ab), 3)
         ELSE 0.0 END AS calc_slg
FROM players p
JOIN team_batting_stats b ON p.player_uid = b.player_uid
JOIN teams t ON b.team_id = t.team_id
JOIN leagues l ON t.league_id = l.league_id
GROUP BY p.player_uid;

-- 跨季球員投球生涯總表 View（同時提供 7 局制少棒基準與 9 局制對齊網站基準）
CREATE VIEW IF NOT EXISTS v_player_career_pitching AS
SELECT
    p.player_uid,
    p.masked_name,
    p.birth_ym,
    COUNT(DISTINCT pt.team_id) AS seasons_pitched,
    GROUP_CONCAT(DISTINCT l.age_group) AS age_groups,
    SUM(pt.w) AS w,
    SUM(pt.l) AS l,
    SUM(pt.sv) AS sv,
    SUM(pt.g) AS g,
    SUM(pt.outs) AS total_outs,
    printf('%d.%d', SUM(pt.outs) / 3, SUM(pt.outs) % 3) AS ip_baseball,
    ROUND(SUM(pt.outs) / 3.0, 2) AS ip_decimal,
    SUM(pt.ab) AS ab,
    SUM(pt.h) AS h,
    SUM(pt.hr) AS hr,
    SUM(pt.bb) AS bb,
    SUM(pt.so) AS so,
    SUM(pt.r) AS r,
    SUM(pt.er) AS er,
    CASE WHEN SUM(pt.outs) > 0
         THEN ROUND((SUM(pt.er) * 27.0) / SUM(pt.outs), 2)
         ELSE NULL END AS calc_era_9,
    CASE WHEN SUM(pt.outs) > 0
         THEN ROUND((SUM(pt.er) * 21.0) / SUM(pt.outs), 2)
         ELSE NULL END AS calc_era_7,
    CASE WHEN SUM(pt.outs) > 0
         THEN ROUND(((SUM(pt.h) + SUM(pt.bb)) * 3.0) / SUM(pt.outs), 2)
         ELSE NULL END AS calc_whip,
    CASE WHEN SUM(pt.outs) > 0
         THEN ROUND((SUM(pt.so) * 21.0) / SUM(pt.outs), 2)
         ELSE NULL END AS calc_k7
FROM players p
JOIN team_pitching_stats pt ON p.player_uid = pt.player_uid
JOIN teams t ON pt.team_id = t.team_id
JOIN leagues l ON t.league_id = l.league_id
GROUP BY p.player_uid;
```

---

## 三、 對應 Python 實作計畫

### 1. 專案目錄與模組結構

```text
pirates-baseball-db/
├── AGENTS.md                   # 專案規範（爬蟲禮儀 >=1.5s、本地快取、outs/player_uid 規範）
├── IMPLEMENTATION_PLAN.md      # 本規格書
├── requirements.txt            # httpx, beautifulsoup4, lxml, pandas, streamlit, plotly, tenacity
├── data/
│   ├── 海盜隊網頁標題.csv       # 種子清單 (41 筆)
│   ├── raw_html/               # HTML 快取：{league_id}_{team_id}.html
│   └── pirates.db              # SQLite 資料庫
├── src/
│   ├── __init__.py
│   ├── db.py                   # 連線管理、Schema 與 Views 建立、Upsert 輔助函式
│   ├── seed_loader.py          # 解析 CSV 與標題萃取聯賽/分隊維度欄位
│   ├── fetch.py                # 禮貌下載 HTML 快取（單線程、延遲 1.5~2.5s、斷點續傳）
│   ├── parse.py                # HTML DOM 解析與寫入 SQLite
│   ├── verify.py               # 資料完整性與邏輯交叉驗算腳本
│   └── app.py                  # Streamlit 台中小海盜戰情與成長查詢儀表板
└── run_pipeline.py             # CLI 一鍵執行管線（支援 --refresh-year 與 --parse-only）
```

---

### 2. 各模組詳細實作規格

#### A. `src/seed_loader.py`（種子清單預處理）
- **輸入**：`data/海盜隊網頁標題.csv`（務必使用 `encoding="utf-8-sig"` 讀取，處理 BOM）。
- **URL 解析**：去除 `#team-section`，以 `urllib.parse` 提取 `league_id`（即 `game_id`）與 `team_id`。
- **標題正則萃取（必須涵蓋全數 41 筆變體）**：
  - `year`：擷取開頭 4 位數字（`2024` / `2025` / `2026`）。
  - `season`：包含 `春季` -> `'春季'`；包含 `秋季` -> `'秋季'`；其餘 -> `'其他'`。
  - `tournament_type`：包含 `台灣大賽` -> `'台灣大賽'`；包含 `季後賽` -> `'季後賽'`；其餘 -> `'例行賽'`。
  - `age_group`：正規表示式 `r"(U(?:8|10|12|15))"` 萃取 `'U8'` / `'U10'` / `'U12'` / `'U15'`。
  - `division`：包含 `大聯盟` -> `'大聯盟'`；包含 `小聯盟` -> `'小聯盟'`；其餘 -> `'一般'`。
  - `team_group`：依 `原始連結文字` 分類：
    - `台中海盜` -> `'U15海盜'`
    - 含 `(白)` -> `'白隊'`
    - 含 `(黑)` -> `'黑隊'`
    - `台中小海盜` -> `'海盜本隊'`

#### B. `src/fetch.py`（禮貌下載與本地快取）
- **快取路徑**：`data/raw_html/{league_id}_{team_id}.html`。
- **更新與斷點續傳邏輯**：
  - 預設：檔案若已存在且非空則跳過（不重複請求網站）。
  - 支援參數 `--refresh-year 2026` 或 `--force`：僅針對進行中的年度／指定 `team_id` 重新下載覆蓋。
- **HTTP 禮貌機制**：
  - 使用 `httpx.Client`（單線程循序請求，設定明確 `User-Agent` 與 `timeout=20.0`）。
  - 搭配 `tenacity` 對暫時性網路錯誤（5xx / Timeout）進行最多 3 次重試。
  - 每次實際發出網路請求後強制 `time.sleep(random.uniform(1.5, 2.5))`。

#### C. `src/parse.py`（高容錯 HTML 解析與入庫）
解析過程一律只讀取 `data/raw_html/` 中的本地 HTML（`BeautifulSoup(html, "lxml")`），單隊資料以單一 SQLite Transaction 包裝：

1. **寫入 `leagues` 與 `teams`**
   - 多隊共用同一 `league_id`（例如白隊、黑隊同屬 `430`）時，對 `leagues` 使用 `ON CONFLICT(league_id) DO UPDATE`。
   - 提取教練團區塊（領隊、總教練、管理、教練）更新至 `teams`。
2. **解析「球員名冊」建立當隊身分映射表**
   - 定位包含 `背號`、`姓名`、`守位`、`生日` 的表格。
   - 檢查 `姓名` 儲存格內是否含有 `<a href="...">`，若有則以正則提取 `player_id` 作為 `site_player_id`；若無則組合成 `player_uid = f"{masked_name}_{birth_ym}"`（若生日亦為空則記錄 Warning 並用 `f"{masked_name}_team{team_id}_{jersey_number}"` 作為最後防線）。
   - Upsert 寫入 `players` 與 `team_rosters`。
   - 建立當隊記憶體對照字典 `roster_lookup[(jersey_number, masked_name)] = player_uid` 與 `name_lookup[masked_name] -> list[player_uid]`。
3. **解析「賽程及結果」（強制去重）**
   - 尋找「本次賽事賽程及結果」對應表格時，**僅取第一個出現的表格**（忽略網站重複渲染的第 2~5 份 DOM）。
   - 解析 `日期`、`時間`、`賽事`（依 `vs.` 或欄位拆分 `away_team` / `home_team`）、`場地`、`結果`（若為 `:` 或空白則比分存 `NULL`；若為 `8 : 3` 則轉整數）。
   - 搭配 `leagues.year` 將 `MM/DD` 轉換為 `YYYY-MM-DD` 存入 `match_date_iso`（註：檢查秋季跨年賽事如 12 月/1 月邊界）。
   - 提取同列連結中的 `攻守數據`、`文字紀錄`、`戰況表` 絕對網址存入 `matches`。
4. **解析「球隊打者表現」與「球隊投手表現」**
   - 依表頭識別表格（將表頭空白與全形字元正規化，例如將全形 `Ｇ` 轉為半形 `G`，並搭配是否含 `PA`/`OBP` 區分打者表、是否含 `IP`/`ERA` 區分投手表）。
   - 拆分 `Player` 欄位（正則 `r"^\s*(\d*)\s*(.+?)\s*$"` 拆出 `jersey_number` 與 `masked_name`）。
   - 透過 `roster_lookup.get((jersey_number, masked_name))` 精準對齊 `player_uid`；若名冊無此人（罕見漏登錄狀況），若 `name_lookup` 僅有唯一人選則沿用，否則新建玩家記錄並印出 Warning。
   - 投手 `IP` 換算：`outs = round(float(ip_raw) * 3)`（防呆：檢查空字串或 `-` 視為 `0`）。
   - 解析頁尾 `Top 10 - Batting` 表格中的盜壘數據，回填至對應球員 `team_batting_stats.sb_top10`。
   - 遇到 `<tbody>` 為空的未開賽頁面（如 `team_id=4046`），安靜完成 `teams` 與 `leagues` 建檔，不中斷流程。

#### D. `src/verify.py`（自動化驗算與異常報告）
實作獨立驗證指令，產出清楚的 Console 報告，包含以下檢查項目：
1. **覆蓋率檢查**：`leagues` 表筆數、確認 `teams` 剛好有 41 筆（對應 CSV 1–41 號），並列出 0 名冊／0 賽程的隊伍名單（預期僅未開賽隊伍）。
2. **同名歸戶檢查**：驗證 `team_id=3439`（2026 春季 U10 白A）中確實存在兩個獨立的 `蔡〇宇` `player_uid`（`2015-11` 與 `2017-06`），且各自的投打數據無合併覆蓋錯誤。
3. **跨屆升組串聯驗證**：檢查 `2024` / `2025` `台中小海盜` 升上 `2026` `台中海盜`（U15）的選手（如 `黃〇軒`、`簡〇承` 等）是否成功共用同一 `player_uid`。
4. **棒球邏輯與數值驗算**：
   - 檢查是否有 `h > ab`、`ab > pa`、負數值。
   - 驗證 `outs` 還原回小數局數與 `ip_raw` 誤差皆 `<= 0.02`。
   - 比對資料庫重算的 `calc_avg` / `calc_slg` 與網站 `site_avg` / `site_slg` 差異是否 `<= 0.002`（驗證進位誤差內一致）；並記錄 `site_obp` 計算公式差異（確認網站 `BB` 是否含觸身球或計算基準為 `PA` vs `AB+BB`）。
   - 特別驗證 `team_id=3439` 中 `IP = 0.00, ER = 1`（林〇晏）之紀錄已正確保存 `outs=0, er=1`，不會在合併 ERA 時遺失責失分。

#### E. `src/app.py`（Streamlit 台中小海盜專屬查詢看板）
採用 `streamlit` + `plotly` 連接 `data/pirates.db`（唯讀模式查詢），全域左側邊欄提供 **「層級複選開關（U8 / U10 / U12 / U15）」** 與 **「分隊群組複選開關（海盜本隊 / 白隊 / 黑隊 / U15海盜）」** 以及 **「年度／季節／賽制篩選器」**，設計 4 個核心頁面：
1. **分隊戰情總覽**：
   - 顯示符合篩選條件的總勝／敗／和、場均得分／失分、團隊打擊三圍與團隊 ERA（可切換 **7局制／9局制**），並列出各聯賽分隊戰績明細表。
2. **投打排行榜**：
   - 分「打者榜」與「投手榜」兩分頁，支援 **最低打席（PA）** 與 **最低投球局數（IP）** 滑桿門檻過濾小樣本。
   - 提供複選切換：檢視「單季分隊成績」或「符合條件的跨季合併成績」，可依 OPS、AVG、HR、BB/K、ERA、WHIP、K/7 排序並匯出 CSV。
3. **球員跨屆成長檔案（Player Profile）**：
   - 透過「遮罩姓名（＋出生年月）或背號」搜尋並選定單一球員。
   - 自動列出該球員從 U8 -> U10 -> U12 -> U15（含黑白分隊與 U15 台中海盜）的所有歷屆出賽紀錄表。
   - 使用 Plotly 繪製「歷屆 OPS / AVG 成長折線圖」與「歷屆 ERA / WHIP / K/7 趨勢圖」。
4. **賽程戰果與對戰對手分析**：
   - 支援輸入或下拉選擇對手球隊（如 `健行小牛`、`台中道奇` 等），即時統計台中小海盜各層級對戰該對手的歷年勝敗紀錄、總得失分與單場比分列表（並顯示預留的 `攻守數據` 連結供點擊查看）。

---

## 四、 驗收標準（Acceptance Criteria）

1. 執行 `python run_pipeline.py` 可完整跑完 41 頁快取下載（耗時約 1.5 分鐘）、解析入庫至 `data/pirates.db` 及 `verify.py` 驗算無嚴重 Error。
2. 再次執行 `python run_pipeline.py` 時，因快取存在會於數秒內完成冪等（Idempotent）重跑，資料庫筆數不會膨脹重複。
3. 啟動 `streamlit run src/app.py` 後，於瀏覽器驗證：
   - 勾選／取消勾選 `U15` 或 `台中海盜` 開關，數據與名單即時連動變化。
   - 搜尋 `蔡〇宇` 能清楚區分 `2015-11` 與 `2017-06` 兩位不同選手。
   - 所有分頁、篩選器與 Plotly 圖表無任何 Exception 或報錯。