@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Lancer-AutoLoot.ps1"
if errorlevel 1 pause
