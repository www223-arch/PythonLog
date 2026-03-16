@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ========================================
echo Python上位机可移植打包脚本
echo ========================================
echo.

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

:: 1. 选择或创建虚拟环境（优先 .venv，其次 venv）
echo [1/5] 准备虚拟环境...
set VENV_PATH=
if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" set VENV_PATH=%SCRIPT_DIR%.venv
if "%VENV_PATH%"=="" if exist "%SCRIPT_DIR%venv\Scripts\python.exe" set VENV_PATH=%SCRIPT_DIR%venv

if "%VENV_PATH%"=="" (
    echo 未检测到虚拟环境，创建 .venv ...
    py -3 -m venv .venv >nul 2>nul
    if !errorlevel! neq 0 (
        python -m venv .venv
        if !errorlevel! neq 0 (
            echo 错误：无法创建虚拟环境，请先安装 Python 3 并确保已加入 PATH。
            pause
            exit /b 1
        )
    )
    set VENV_PATH=%SCRIPT_DIR%.venv
)

set PY_EXE=%VENV_PATH%\Scripts\python.exe
set PIP_EXE=%VENV_PATH%\Scripts\pip.exe

echo 使用虚拟环境：%VENV_PATH%
echo.

:: 2. 删除旧打包产物
echo [2/5] 清理旧产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__
echo 清理完成！
echo.

:: 3. 安装依赖（requirements + pyinstaller）
echo [3/5] 安装依赖...
"%PY_EXE%" -m pip install --upgrade pip
if !errorlevel! neq 0 (
    echo pip 升级失败。
    pause
    exit /b 1
)

"%PIP_EXE%" install -r requirements.txt
if !errorlevel! neq 0 (
    echo 安装 requirements.txt 失败。
    pause
    exit /b 1
)

"%PIP_EXE%" install pyinstaller
if !errorlevel! neq 0 (
    echo 安装 PyInstaller 失败。
    pause
    exit /b 1
)
echo 依赖安装完成！
echo.

:: 4. 执行打包
echo [4/5] 执行打包...
"%PY_EXE%" -m PyInstaller main.spec
if !errorlevel! neq 0 (
    echo 打包失败，请检查 main.spec 与依赖。
    pause
    exit /b 1
)
echo 打包完成！
echo.

:: 5. 结果提示
echo [5/5] 产物检查...
if exist dist\Python上位机.exe (
    echo 成功：dist\Python上位机.exe
) else (
    echo 未找到 dist\Python上位机.exe，请检查打包日志。
    pause
    exit /b 1
)

echo.
echo ========================================
echo 打包流程完成
echo ========================================
pause