@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Installer-AutoLoot.ps1"
if errorlevel 1 echo Installation interrompue. Voir le message ci-dessus.
pause
