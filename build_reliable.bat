@echo on  :: 开启命令回显，能看到每一步执行的命令和报错
chcp 65001 >nul  :: 强制UTF-8编码
setlocal enabledelayedexpansion  :: 稳定判断错误码

:: ========== 第一步：配置关键路径（必须改！）==========
:: 替换为你的虚拟环境实际路径（从之前截图看是这个路径）
set VENV_PATH=C:\Users\tk\Desktop\Pythonlog\venv
:: 项目根目录（bat脚本所在目录）
set PROJECT_ROOT=%~dp0

echo ========================================
echo Python上位机打包脚本（可查看执行日志）
echo ========================================
echo 虚拟环境路径：%VENV_PATH%
echo 项目根目录：%PROJECT_ROOT%
echo.

:: ========== 第二步：激活虚拟环境（核心！）==========
echo [1/5] 激活虚拟环境...
if not exist "%VENV_PATH%\Scripts\activate.bat" (
    echo 【错误】虚拟环境不存在！路径：%VENV_PATH%
    pause  :: 出错暂停，不让闪退
    exit /b 1
)
call "%VENV_PATH%\Scripts\activate.bat"
if !errorlevel! neq 0 (
    echo 【错误】激活虚拟环境失败！
    pause
    exit /b 1
)
echo 虚拟环境激活成功！
echo.

:: ========== 第三步：删除旧打包文件 ==========
echo [2/5] 删除旧的打包文件...
if exist "%PROJECT_ROOT%\build" rmdir /s /q "%PROJECT_ROOT%\build"
if exist "%PROJECT_ROOT%\dist" rmdir /s /q "%PROJECT_ROOT%\dist"
if exist "%PROJECT_ROOT%\__pycache__" rmdir /s /q "%PROJECT_ROOT%\__pycache__"
echo 删除完成！
echo.

:: ========== 第四步：检查并安装依赖 ==========
echo [3/5] 检查依赖...
:: 用虚拟环境内的python检查依赖
"%VENV_PATH%\Scripts\python.exe" -c "import PyQt5, pyqtgraph, numpy, pandas, serial" 2>nul
if !errorlevel! neq 0 (
    echo 依赖检查失败！正在安装依赖（清华源）...
    "%VENV_PATH%\Scripts\pip.exe" install -r "%PROJECT_ROOT%\requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
    if !errorlevel! neq 0 (
        echo 【错误】依赖安装失败！请手动激活venv后运行：
        echo pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        pause
        exit /b 1
    )
)
echo 依赖检查通过！
echo.

:: ========== 第五步：用虚拟环境的pyinstaller打包 ==========
echo [4/5] 使用spec文件打包...
cd /d "%PROJECT_ROOT%"  :: 切换到项目根目录（避免路径问题）
"%VENV_PATH%\Scripts\pyinstaller.exe" main.spec
if !errorlevel! neq 0 (
    echo 【错误】打包失败！请查看上方报错信息
    pause
    exit /b 1
)
echo 打包完成！
echo.

:: ========== 第六步：测试可执行文件 ==========
echo [5/5] 测试可执行文件...
if exist "%PROJECT_ROOT%\dist\Python上位机.exe" (
    echo 可执行文件已生成：%PROJECT_ROOT%\dist\Python上位机.exe
    echo 正在测试...
    start "" "%PROJECT_ROOT%\dist\Python上位机.exe"
) else (
    echo 【错误】打包失败，未找到可执行文件！
    pause
    exit /b 1
)
echo.

:: ========== 完成 ==========
echo ========================================
echo 打包流程完成！
echo 可执行文件位置：%PROJECT_ROOT%\dist\Python上位机.exe
echo ========================================
:: 退出虚拟环境
call "%VENV_PATH%\Scripts\deactivate.bat"
pause  :: 最后暂停，防止闪退
endlocal