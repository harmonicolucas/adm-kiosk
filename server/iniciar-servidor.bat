@echo off
chcp 65001 >nul
title ADM Kiosk - Servidor de administracao remota
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python 3 nao encontrado. Instale a partir de https://www.python.org/downloads/
    echo e marque a opcao "Add python.exe to PATH".
    pause
    exit /b 1
)

python adm_kiosk_server.py --port 8080
pause
