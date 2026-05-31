@echo off
chcp 65001 >nul
title 狗三 QQ机器人 一键启动

echo.
echo   🐧 狗三 QQ机器人启动中...
echo   ━━━━━━━━━━━━━━━━━━━━━━
echo.

:: 1. 启动 NapCat（在独立窗口，方便扫码）
echo   [1/2] 启动 NapCat v4.18.4 协议层...
start "NapCat-v4.18.4" /D "D:\桌面\NapCat\NapCat.v4.18.4" "D:\桌面\NapCat\NapCat.v4.18.4\napcat.bat"

:: 2. 等待 NapCat 初始化（WebSocket 就绪需要时间）
echo   [2/2] 等待 NapCat 就绪...（8秒）
timeout /t 8 /nobreak >nul

:: 3. 启动机器人
echo.
echo   ━━━━━━━━━━━━━━━━━━━━━━
echo   🤖 启动 NoneBot 机器人...
echo   ━━━━━━━━━━━━━━━━━━━━━━
echo.

cd /d "d:\桌面\狗三"
python bot.py

pause
