@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ==== 打包出来的程序名，若非 ASCII 名字导致报错，改成英文即可 ====
set "APPNAME=PDF首页转PNG"

rem 有 app.ico 就用作图标
set "ICONOPT="
if exist "app.ico" set "ICONOPT=--icon app.ico"

echo ============================================
echo   %APPNAME%  打包脚本
echo ============================================
echo.

echo [1/3] 检查 Python ...
python --version
if errorlevel 1 (
    echo.
    echo 没找到 python，请先安装 Python 3.10 - 3.12，
    echo 安装时务必勾选 "Add python.exe to PATH"。
    pause
    exit /b 1
)

echo.
echo [2/3] 安装依赖 ...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo 依赖安装失败。
    pause
    exit /b 1
)

echo.
echo [3/3] 开始打包（首次会比较慢，请耐心等待）...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "%APPNAME%" %ICONOPT% ^
    --exclude-module numpy --exclude-module PIL --exclude-module matplotlib ^
    --exclude-module pytest --exclude-module setuptools ^
    pdf_to_png.py
if errorlevel 1 (
    echo.
    echo 打包失败。若提示找不到 PyMuPDF 的动态库，可改用下面这行重试：
    echo     python -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all pymupdf --name "%APPNAME%" pdf_to_png.py
    pause
    exit /b 1
)

echo.
echo ============================================
echo  打包完成： dist\%APPNAME%.exe
echo  这个 exe 可以单独拷走，目标电脑无需装 Python。
echo ============================================
pause
