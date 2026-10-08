@echo off
chcp 65001 >nul
title Nuke 管线工具一键安装向导 - LiangLiangArtist

echo =======================================================
echo          正在为当前用户安装 Nuke 镜头交付管线工具...
echo =======================================================
echo.

set "TARGET_DIR=%USERPROFILE%\.nuke"
set "INIT_FILE=%TARGET_DIR%\init.py"
set "PLUGIN_DIR=%~dp0"
:: 去除路径末尾的斜杠
set "PLUGIN_DIR=%PLUGIN_DIR:~0,-1%"
:: 将 Windows 反斜杠替换为正斜杠以适配 Nuke
set "PLUGIN_DIR_NUKE=%PLUGIN_DIR:\=/%"

if not exist "%TARGET_DIR%" (
    echo [提示] 正在创建用户 Nuke 目录: %TARGET_DIR%
    mkdir "%TARGET_DIR%"
)

if not exist "%INIT_FILE%" (
    echo # Nuke User Init File > "%INIT_FILE%"
)

:: 检查是否已经添加过，避免重复追加
findstr /C:"%PLUGIN_DIR_NUKE%" "%INIT_FILE%" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] 插件路径已存在，无需重复安装！
) else (
    echo. >> "%INIT_FILE%"
    echo # --- LiangLiang Nuke Pipeline Sync Tool --- >> "%INIT_FILE%"
    echo import nuke >> "%INIT_FILE%"
    echo nuke.pluginAddPath(r"%PLUGIN_DIR_NUKE%") >> "%INIT_FILE%"
    echo [OK] 插件路径已成功写入: %INIT_FILE%
)

echo.
echo =======================================================
echo                 恭喜！安装已成功完成！
echo          现在可以打开或重启 Nuke，顶部将显示菜单:
echo                   【UE镜头管线】
echo =======================================================
echo.
pause