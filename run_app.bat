@echo off
chcp 65001 >nul
:: 切換至本專案所在的絕對路徑
cd /d "C:\Users\chinl\OneDrive\文件\就是棒"


.venv\Scripts\streamlit run src/app.py
