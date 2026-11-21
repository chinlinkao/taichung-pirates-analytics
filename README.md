# 🏴‍☠️ 台中小海盜棒球數據庫 (Taichung Pirates Baseball Analytics)

本專案針對「台中就是棒社區棒球聯賽 (2024–2026)」的台中小海盜隊（U8 / U10 / U12 / U15），建立完整的數據爬取、清洗解析、SQLite 入庫與 Streamlit 戰情可視化看板系統。

---

## 🌟 功能特點

1. **數據爬取與快取 (`src/fetch.py`)**：安全合規爬取 myscore 賽事紀錄，落實本地 HTML 快取保護機制與請求間隔。
2. **清洗與入庫 (`src/parse.py`, `src/db.py`)**：
   - 投球局數精確轉換為出局數（整數存儲）。
   - 嚴格識別球員唯一識別碼（`player_uid`），精準區分同名同姓球員。
3. **歷史種子資料匯入 (`src/seed_loader.py`)**：整合歷史 B.csv (打擊) 與 P.csv (投球) 數據。
4. **戰情查詢看板 (`src/app.py`)**：基於 Streamlit + Plotly，提供多層級（U8/U10/U12/U15）、分隊、年度賽事篩選，以及 7 局制/9 局制防禦率動態計算。

---

## 🚀 快速上手 (Quick Start)

### 1. 建立虛擬環境與安裝依賴

```bash
# 建立虛擬環境 (Python 3.11+)
python -m venv .venv

# 啟動虛擬環境 (Windows PowerShell)
.venv\Scripts\Activate.ps1

# 安裝依賴
pip install -r requirements.txt
```

### 2. 執行資料管線 (Pipeline)

```bash
# 情況 A：日常更新（自動重新抓取 2026 最新賽果並入庫校驗）
python run_pipeline.py --refresh-year 2026

# 情況 B：全自動探索新賽事（自動檢索新組別/賽季 -> 增量追加種子清單 -> 抓取解析入庫）
python run_pipeline.py --discover --refresh-year 2026
# 或在 Windows 雙擊執行：
update_all.bat

# 離線快速重構（僅解析本地快取資料庫入庫，不發出網路請求）
run_pipeline_parse_only.bat
```

### 3. 啟動 Streamlit 數據看板

```bash
# 啟動互動式 Web 儀表板（可直接在側邊欄一鍵同步最新戰績與檢視最後更新時間）
run_app.bat
# 或手動執行：
streamlit run src/app.py
```

---

## 📂 專案結構說明

```text
├── .gitignore               # Git 忽略檔案設定 (.venv, data/raw_html 快取等)
├── AGENTS.md                # 專案規範與資料模型準則
├── requirements.txt         # 專案依賴清單
├── run_app.bat              # 一鍵啟動 Streamlit 看板腳本
├── run_pipeline.py          # 數據管線總進入點 (支援 --discover, --refresh-year)
├── update_all.bat           # 一鍵自動探索新賽事、更新快取與入庫驗證
├── src/
│   ├── app.py               # Streamlit 數據看板主程式 (含同步按鈕與更新時間顯示)
│   ├── db.py                # SQLite 資料庫初始化與連線
│   ├── discovery.py         # 自動探索新賽事與增量更新 CSV (整合原 find 與 scrape 腳本)
│   ├── fetch.py             # 賽事原始 HTML 爬蟲模組
│   ├── parse.py             # 比賽攻守與球員數據解析
│   ├── seed_loader.py       # 歷史 CSV 種子資料加載器
│   └── verify.py            # 數據完整性與跨表驗證腳本
└── data/
    ├── pirates.db           # SQLite 數據庫
    └── 海盜隊網頁標題.csv   # 聯賽種子清單
```

---

## ☁️ 部署到雲端 (Streamlit Community Cloud)

1. 將本專案推送到 GitHub。
2. 登入 [Streamlit Community Cloud](https://share.streamlit.io/)。
3. 點選 **"New app"**，選擇您的 GitHub 儲存庫：
   - **Main file path**: `src/app.py`
4. 點選 **"Deploy"**，即可免費獲得可線上分享的數據戰情看板！
