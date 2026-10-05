@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
)

if not exist ".venv\.ready" (
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 pause & exit /b 1
  type nul > ".venv\.ready"
)

".venv\Scripts\python.exe" -m streamlit run app.py --server.port 8502 --server.headless false

