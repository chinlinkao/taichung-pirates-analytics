@echo off
chcp 65001 >nul
:: 切換至本專案所在的絕對路徑
cd /d "C:\Users\chinl\OneDrive\文件\就是棒"

echo ============================================================
echo 正在執行台中小海盜棒球數據解析管線 (--parse-only)...
echo ============================================================

:: 呼叫專案虛擬環境中的 python 執行 run_pipeline.py
".venv\Scripts\python.exe" run_pipeline.py --parse-only

echo.
echo 執行完畢，按任意鍵關閉視窗...
pause >nul
