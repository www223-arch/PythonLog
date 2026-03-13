@echo off
:: 强制设置编码为UTF-8+BOM（解决中文乱码）
chcp 65001 >nul
:: 关闭命令回显（避免冗余输出）
@setlocal enabledelayedexpansion

echo ========================================
echo Python上位机打包脚本
echo ========================================
echo.

:: ******** 关键：指定虚拟环境路径（和你的实际路径一致）********
set VENV_PATH=C:\Users\tk\Desktop\Pythonlog\venv

:: 1. 激活虚拟环境（解决pyinstaller路径问题）
echo [1/5] 激活虚拟环境...
if not exist "%VENV_PATH%\Scripts\activate.bat" (
    echo 错误：虚拟环境不存在！路径：%VENV_PATH%
    pause
    exit /b 1
)
call "%VENV_PATH%\Scripts\activate.bat"
echo 虚拟环境激活成功！
echo.

:: 2. 删除旧打包文件
echo [2/5] 删除旧打包文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__
echo 删除完成！
echo.

:: 3. 检查并安装依赖（用venv内的pip，清华源加速）
echo [3/5] 检查依赖...
"%VENV_PATH%\Scripts\python.exe" -c "import PyQt5, pyqtgraph, numpy, pandas, serial" 2>nul
if !errorlevel! neq 0 (
    echo 依赖缺失，开始安装...
    "%VENV_PATH%\Scripts\pip.exe" install PyQt5==5.15.2 pyqtgraph==0.14.0 numpy==2.4.3 pandas==3.0.1 pyserial==3.5 -i https://pypi.tuna.tsinghua.edu.cn/simple
    if !errorlevel! neq 0 (
        echo 依赖安装失败！请手动激活venv后执行：
        echo pip install PyQt5==5.15.2 pyqtgraph==0.14.0 numpy==2.4.3 pandas==3.0.1 pyserial==3.5 -i https://pypi.tuna.tsinghua.edu.cn/simple
        pause
        exit /b 1
    )
)
echo 依赖检查通过！
echo.

:: 4. 用venv内的pyinstaller打包（解决命令未识别）
echo [4/5] 执行打包...
"%VENV_PATH%\Scripts\pyinstaller.exe" main.spec
if !errorlevel! neq 0 (
    echo 打包失败！请检查spec文件
    pause
    exit /b 1
)
echo 打包完成！
echo.

:: 5. 测试可执行文件
echo [5/5] 测试可执行文件...
if exist dist\Python上位机.exe (
    echo 可执行文件路径：dist\Python上位机.exe
    start dist\Python上位机.exe
) else (
    echo 未找到可执行文件，打包失败！
    pause
    exit /b 1
)
echo.

echo ========================================
echo 打包流程完成！
echo ========================================
:: 退出虚拟环境
call "%VENV_PATH%\Scripts\deactivate.bat"
pause