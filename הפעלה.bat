@echo off
rem Double-click to start the app. The API key is read from the GOOGLE_API_KEY user variable (set once with setx).
cd /d "%~dp0"
".venv\Scripts\streamlit.exe" run app.py
pause
