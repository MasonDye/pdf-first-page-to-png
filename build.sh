#!/usr/bin/env bash
# Linux/macOS 下打包（产物是本平台可执行文件，不是 .exe）
set -e
cd "$(dirname "$0")"
APPNAME="pdf-first-page-image"
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed \
    --name "$APPNAME" \
    --exclude-module numpy --exclude-module PIL --exclude-module matplotlib \
    pdf_to_png.py
echo "完成: dist/$APPNAME"
