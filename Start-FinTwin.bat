@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-fintwin.ps1"
if errorlevel 1 pause
