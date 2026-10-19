@echo off
rem Duplo clique: liga o dashboard no monitor vertical. Para desligar: Alt+F4 no dashboard.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0tools\iniciar_dashboard.ps1"
