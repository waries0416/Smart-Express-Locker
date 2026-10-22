@echo off
chcp 65001 >nul
REM ===========================================================================
REM 本地一键启动（不依赖内网穿透）
REM   · 触屏端：http://127.0.0.1:5000/
REM   · 管理端：http://127.0.0.1:5000/admin
REM   · 手机端：http://127.0.0.1:5000/m  （手机需与本机同一 Wi-Fi）
REM 需要手机在校园网/流量下也能扫开二维码时，改用 scripts\start-with-tunnel.bat
REM ===========================================================================
cd /d "%~dp0.."

set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [!] 未找到 .venv，改用系统 python（请确认已装 flask / pymysql / dbutils / segno）
    set "PY=python"
)

if "%PORT%"=="" set "PORT=5000"

echo.
echo ==================== 智能快递柜 · 启动中 ====================
echo   触屏端（默认首页）  http://127.0.0.1:%PORT%/
echo   管理端（需登录）    http://127.0.0.1:%PORT%/admin
echo   手机端 H5           http://127.0.0.1:%PORT%/m
echo   演示账号            管理员 admin / admin123
echo                       用户   15800000001（手机端验证码登录）
echo                       快递员 E00001 / 13900000001
echo ------------------------------------------------------------
echo   停止服务：在本窗口按 Ctrl+C
echo ============================================================
echo.

"%PY%" backend\app.py
pause
