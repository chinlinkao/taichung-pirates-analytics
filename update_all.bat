@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================================
echo  台中小海盜棒球數據 - 全自動探索、更新與建置流程
echo ==========================================================
echo.

.venv\Scripts\python.exe run_pipeline.py --discover --refresh-year 2026

echo.
pause
