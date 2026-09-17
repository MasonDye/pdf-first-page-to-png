# PDF 首页转 PNG

[![Build Windows EXE](https://github.com/MasonDye/pdf-first-page-to-png/actions/workflows/build-windows.yml/badge.svg)](https://github.com/MasonDye/pdf-first-page-to-png/actions/workflows/build-windows.yml)

把指定文件夹下所有 PDF 的**第一页**导出为 PNG 图片，保存到指定输出文件夹，**图片名与原 PDF 同名**
（`合同扫描件.pdf` → `合同扫描件.png`）。

带图形界面，也可以命令行调用；用 PyInstaller 打包成单个 `.exe`，目标电脑无需安装 Python。

---

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `pdf_to_png.py` | 程序本体（GUI + 命令行） |
| `requirements.txt` | 依赖：PyMuPDF |
| `build.bat` | **Windows 一键打包 exe**（双击即可） |
| `build.sh` | Linux/macOS 打包（产物是本平台可执行文件，非 exe） |
| `app.ico` | 可选。放一个同名图标文件，打包时会自动使用 |
| `.github/workflows/build-windows.yml` | GitHub Actions：每次 push 自动在 Windows 上打包并产出 exe |

---

## 下载现成的 exe（推荐）

不想自己装 Python，直接拿 GitHub Actions 构建好的：

1. 打开 [Actions → Build Windows EXE](https://github.com/MasonDye/pdf-first-page-to-png/actions/workflows/build-windows.yml)
2. 点进最上面那次绿色 ✓ 的运行记录
3. 页面底部 **Artifacts** 区域下载 `PDF-First-Page-To-PNG-windows-x64`
4. 解压得到 `PDF-First-Page-To-PNG.exe`，双击即可运行

> 💡 GitHub 要求**登录账号**才能下载 Artifact；构建产物保留 90 天。
> 每次 push 到 `main` 会自动重新构建，也可以在 Actions 页面点 **Run workflow** 手动触发。

CI 里还会做一次自检：用打包好的 exe 转换一个两页的测试 PDF，确认 exe 能独立运行、
输出文件名与 PDF 同名、且每个 PDF 只产出一张图（只取第一页）——自检不过构建就会失败。

---

## 自己在 Windows 上打包 .exe

> PyInstaller 不能跨平台交叉编译：**要 .exe 就必须在 Windows 上打包**。

1. 安装 Python 3.10 ~ 3.12（[python.org](https://www.python.org/downloads/windows/)），
   安装界面务必勾选 **Add python.exe to PATH**。
2. 把本文件夹整个拷到 Windows 上。
3. 双击 **`build.bat`**，等待结束。
4. 产物在 `dist\PDF首页转PNG.exe`，单文件（约 40–70 MB），可以直接拷给别人用。

> 本地打包出来的是中文名 `PDF首页转PNG.exe`；Actions 为避免编码问题用英文名 `PDF-First-Page-To-PNG.exe`，两者内容一致。

打包脚本实际执行的命令是：

```bat
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "PDF首页转PNG" ^
    --exclude-module numpy --exclude-module PIL --exclude-module matplotlib ^
    pdf_to_png.py
```

> ⚠️ 若打包报错提示找不到 PyMuPDF 的动态库，把 `--exclude-module ...` 换成 `--collect-all pymupdf` 重试。
> ⚠️ 若因中文程序名报错，编辑 `build.bat` 第 6 行把 `APPNAME` 改成英文。

---

## 使用（图形界面）

双击 exe 后：

```
┌──────────────────────────────────────────────┐
│ PDF 文件夹 : D:\发票            [浏览…]       │
│ 输出文件夹 : D:\发票\png        [浏览…]       │
├──────────────────────────────────────────────┤
│ 分辨率 DPI: [150 ▾]   同名文件: [自动重命名 ▾] │
│ □ 包含子文件夹      □ 输出时保留子目录结构     │
├──────────────────────────────────────────────┤
│ 日志: [1/20] ✓ 发票001.pdf → 发票001.png ...  │
├──────────────────────────────────────────────┤
│ [====progress====] 20/20  [开始转换][停止][打开输出目录] │
└──────────────────────────────────────────────┘
```

- **分辨率 DPI**：150 适合一般预览，300 适合打印/放大；数值越大图越清晰、文件越大。
- **同名文件**：目标 PNG 已存在时 —— 自动重命名（`name_1.png`）／覆盖／跳过。
- **包含子文件夹**：递归处理所有层级的 PDF；勾上后可再选择**保留子目录结构**
  （不保留则全部平铺到输出目录，重名按上一条规则处理）。
- 上次用的路径和选项会自动记住（存在 `%USERPROFILE%\.pdf_first_page_png.json`）。
- 加密 PDF、损坏文件会在日志里标红跳过，不会中断整批任务。

---

## 使用（命令行）

从源码运行时可直接传参，不弹界面：

```bash
python pdf_to_png.py <输入文件夹> <输出文件夹> [选项]

  --dpi N                    输出分辨率，默认 150
  -r, --recursive            递归处理子文件夹
  --keep-tree                递归时在输出目录保留子目录结构
  --on-exist overwrite|skip|rename   同名 PNG 的处理方式，默认 rename
```

示例：

```bash
python pdf_to_png.py "D:\发票" "D:\发票\png" --dpi 300 -r --on-exist overwrite
```

退出码：全部成功 `0`，有文件失败 `1`，参数/路径错误 `2`。

> 注意：`build.bat` 用 `--windowed` 打包（无黑框窗口），所以 **exe 以命令行方式运行时不会输出文字**。
> 需要在 exe 上用命令行，把 `build.bat` 里的 `--windowed` 换成 `--console` 重新打包即可。

---

## 直接跑源码（不打包）

```bash
pip install -r requirements.txt
python pdf_to_png.py          # 启动图形界面
```

依赖只有 PyMuPDF，**不需要**安装 poppler / Ghostscript 等外部程序。
