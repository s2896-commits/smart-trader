@echo off
cd /d L:\Smart_Trader
start http://localhost:8000
L:\Smart_Trader\venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8000
