@echo off
chcp 65001 >nul
REM 一键启动：Flask + cloudflared 内网穿透（手机扫柜机二维码走公网）
REM 详细说明见同目录 start-with-tunnel.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-with-tunnel.ps1" %*
