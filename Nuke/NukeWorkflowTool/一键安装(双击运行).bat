@echo off
chcp 65001 >nul
title Nuke 管线工具一键安装向导

set "TARGET_DIR=%USERPROFILE%\.nuke"
set "INIT_FILE=%TARGET_DIR%\init.py"

:: 获取当前目录并强制将 Windows 反斜杠 \ 转为 Python 安全正斜杠 /
set "RAW_DIR=%~dp0"
set "RAW_DIR=%RAW_DIR:~0,-1%"
set "SAFE_DIR=%RAW_DIR:\=/%"

if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

:: 如果已有内容，先安全追加，使用正斜杠写入
echo. >> "%INIT_FILE%"
echo import nuke >> "%INIT_FILE%"
echo nuke.pluginAddPath('%SAFE_DIR%') >> "%INIT_FILE%"

echo =======================================================
echo [OK] 插件路径已成功安全写入: %INIT_FILE%
echo 写入路径: %SAFE_DIR%
echo =======================================================
pause