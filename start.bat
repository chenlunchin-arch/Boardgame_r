@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 桌遊推薦 APP
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo [錯誤] 找不到 Python，請先安裝 Python 3.10 以上版本，安裝時勾選 Add Python to PATH
    pause
    exit /b 1
  )
  set "PY=py -3"
)

if not exist ".venv\Scripts\python.exe" (
  echo [第一次執行] 建立虛擬環境並安裝套件，請稍候...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [錯誤] 無法建立虛擬環境。若 python 是 Microsoft Store 的捷徑，請改從 python.org 安裝
    pause
    exit /b 1
  )
)

rem 套件不完整（例如上次安裝中斷）就重新安裝
".venv\Scripts\python.exe" -c "import flask, waitress, openpyxl, sqlalchemy" >nul 2>nul
if errorlevel 1 (
  echo [安裝] 正在安裝或修復套件，請稍候...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
  if errorlevel 1 (
    echo [錯誤] 套件安裝失敗，請確認網路連線後再執行一次
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" app.py
pause
