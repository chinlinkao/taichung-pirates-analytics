@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================================
echo  🏴‍☠️ 台中小海盜棒球數據 - 全面探索全新賽事並同步至雲端
echo ==========================================================
echo.
echo 說明：此腳本會重新連線 myscore.games 掃描全聯賽是否有全新組別/網址，
echo       適合在新賽季開打、增加全新隊伍時執行一次。
echo.

call .venv\Scripts\python.exe -u run_pipeline.py --discover --refresh-year 2026

if errorlevel 1 (
    echo.
    echo [!] 數據管線執行失敗，請檢查錯誤訊息，取消同步至雲端。
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo [2/3] 本機數據庫更新成功！準備推送至 GitHub...
echo ==========================================================
echo.

git add .
git diff-index --quiet HEAD
if errorlevel 1 (
    git commit -m "update: 全面探索並同步最新賽事數據"
)
git pull --rebase origin main
git push origin main

if errorlevel 1 (
    echo.
    echo [!] Git 推送失敗，請確認網路連線或 GitHub 權限。
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo [3/3] 全流程完成！
echo 數據已成功推送到 GitHub，Streamlit Cloud 正在自動更新線上看板！
echo 線上網址: https://taichung-pirates-analytics-8daxykwaebdotzf79m37ya.streamlit.app/
echo ==========================================================
echo.
pause
