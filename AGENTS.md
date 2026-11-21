# 台中小海盜數據專案規範 (AGENTS.md)

## 1. 執行環境與語言
- 使用 Python 3.11+（`.venv` 虛擬環境），繁體中文撰寫註解與回覆。
- CSV 讀取一律使用 `encoding="utf-8-sig"`；SQLite 連線必須開啟 `PRAGMA foreign_keys = ON;`。

## 2. 爬蟲安全紅線
- 對 `myscore.games` 採單線程循序請求，每次請求間隔必須 >= 1.5 秒，嚴禁高併發。
- 下載之原始網頁一律先快取至 `data/raw_html/`，修改或重跑 `parse.py` 時只能讀取本地快取，禁止重新請求網站。

## 3. 棒球數據模型鐵則
- 球員唯一識別必須使用 `player_uid`（`id:{site_player_id}` 或 `{masked_name}_{birth_ym}`），嚴禁僅用遮罩姓名合併數據。
- 投球局數入庫一律轉換為整數出局數 `outs = round(float(ip) * 3)`，禁止用小數局數直接加總。
- 每次修改解析邏輯後，必須執行 `python src/verify.py` 驗證通過才算完成。