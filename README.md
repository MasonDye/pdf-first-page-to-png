# PDF 首页转 PNG

[![Build Windows EXE](https://github.com/MasonDye/pdf-first-page-to-png/actions/workflows/build-windows.yml/badge.svg)](https://github.com/MasonDye/pdf-first-page-to-png/actions/workflows/build-windows.yml)

批量提取 PDF 封面：扫描所选文件夹**及其全部子文件夹**里的每一个 PDF，把第一页导出为 PNG，
**直接存回该 PDF 自己所在的文件夹**，文件名与 PDF 相同。

```
【6000本历年高评分书籍合集】/ 00001-01000 / 03651-03700 / cccccc/   ← 选这一层就行
├── 【03658】樱花创造日本_佐藤俊树/
│     ├── 樱花创造日本.pdf
│     └── 樱花创造日本.png     ← 自动生成在这里，不用指定输出目录
├── 【03659】欢乐数学_本·奥尔林/
│     ├── 欢乐数学.pdf
│     └── 欢乐数学.png
└── 【03660】欢喜：女性、革命和一个逝去的男孩_达契亚·玛拉依妮/
      ├── 欢喜：女性、革命和一个逝去的男孩.pdf
      └── 欢喜：女性、革命和一个逝去的男孩.png
```

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

CI 里还会做一次自检：按「每本书一个文件夹」的结构造一个两页的测试 PDF，用打包好的 exe 处理，
断言封面 PNG 出现在**该 PDF 所在的文件夹**里、文件名与 PDF 同名、且整棵目录树只多出一张图
（即只取第一页）——自检不过构建就会失败。

---

## 使用（图形界面）

双击 exe 后：

```
┌─ PDF 文件夹 ───────────────────────────────────────────────────┐
│ [ F:\电子书\【6000本…】\00001-01000\03651-03700\cccccc ] [浏览…][重新扫描] │
│ 封面 PNG 会直接存回每个 PDF 所在的文件夹，文件名与 PDF 相同；所有子文件夹一并处理。 │
├─ 选项 ─────────────────────────────────────────────────────────┤
│ 分辨率 DPI: [150 ▾]      已存在同名 PNG 时: [跳过已存在的 ▾]           │
├─ 文件列表 ─────────────────────────────────────────────────────┤
│ 共 5 个 PDF │ 待提取 0  提取完成 4  已跳过 1  失败 0                  │
│ ┌───────────────────────┬──────────────────┬──────────────────┐ │
│ │ PDF 文件               │ 状态              │ 所在文件夹        │ │
│ ├───────────────────────┼──────────────────┼──────────────────┤ │
│ │ 樱花创造日本.pdf        │ 提取完成          │ 【03658】樱花创造… │ │
│ │ 欢乐数学.pdf           │ 提取完成          │ 【03659】欢乐数学… │ │
│ │ 欢喜：女性、革命和…pdf  │ 提取中…           │ 【03660】欢喜：女… │ │
│ │ 欢迎来到实力至上…pdf    │ 已跳过：同名 PNG 已存在 │ 【03661】欢迎来到… │ │
│ └───────────────────────┴──────────────────┴──────────────────┘ │
├────────────────────────────────────────────────────────────────┤
│ [======progress======] 完成 成功 4 跳过 1 失败 0 [开始转换][停止][打开文件夹] │
└────────────────────────────────────────────────────────────────┘
```

操作只有两步：**选文件夹 → 点开始转换**。

- 选完文件夹会**立即扫描并列出**所有待转换的 PDF（文件名 + 所在子文件夹），状态为「待提取」。
- 开始转换后，每行状态实时变成「提取中…」→「提取完成」／「已跳过」／「失败：原因」，
  列表自动滚动到当前处理的文件，底部进度条和计数同步更新。
- **双击任意一行**可以在资源管理器里打开那个 PDF 所在的文件夹。
- **分辨率 DPI**：150 适合一般预览，300 适合打印/放大；数值越大图越清晰、文件越大。
- **已存在同名 PNG 时**：默认「跳过已存在的」——中断后重跑只补没做过的，不会产生重复文件；
  想重新生成就选「覆盖已有文件」。
- 上次用的文件夹和选项会自动记住（存在 `%USERPROFILE%\.pdf_first_page_png.json`）。
- 加密 PDF、损坏文件会在列表里标红显示失败原因，不会中断整批任务。
- Windows 上超过 260 字符的深层路径也能正常处理（自动加 `\\?\` 前缀）。

---

## 使用（命令行）

从源码运行时可直接传参，不弹界面：

```bash
python pdf_to_png.py <PDF文件夹> [选项]

  --dpi N                 输出分辨率，默认 150
  --on-exist skip|overwrite|rename    同名 PNG 的处理方式，默认 skip
  --no-recursive          只处理顶层，不进子文件夹
  -o, --out 文件夹         另存到指定文件夹（不给则存回每个 PDF 自己的目录）
  --keep-tree             配合 -o：在输出目录里保留子目录结构
```

示例：

```bash
# 默认：递归整个书库，封面存回每本书自己的文件夹
python pdf_to_png.py "F:\电子书\【6000本历年高评分书籍合集】" --dpi 300

# 需要时也可以把所有封面集中到一处
python pdf_to_png.py "F:\电子书" -o "D:\封面" --on-exist rename
```

退出码：全部成功 `0`，有文件失败 `1`，参数/路径错误 `2`。

> 注意：`build.bat` 用 `--windowed` 打包（双击不弹黑框），所以 **exe 以命令行方式运行时不会输出文字**。
> 需要在 exe 上用命令行，把 `build.bat` 里的 `--windowed` 换成 `--console` 重新打包即可。

---

## 自己在 Windows 上打包 .exe

> PyInstaller 不能跨平台交叉编译：**要 .exe 就必须在 Windows 上打包**。

1. 安装 Python 3.10 ~ 3.12（[python.org](https://www.python.org/downloads/windows/)），
   安装界面务必勾选 **Add python.exe to PATH**。
2. 把本文件夹整个拷到 Windows 上。
3. 双击 **`build.bat`**，等待结束。
4. 产物在 `dist\PDF首页转PNG.exe`，单文件（约 30–70 MB），可以直接拷给别人用。

> 本地打包出来的是中文名 `PDF首页转PNG.exe`；Actions 为避免编码问题用英文名
> `PDF-First-Page-To-PNG.exe`，两者内容一致。

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

## 直接跑源码（不打包）

```bash
pip install -r requirements.txt
python pdf_to_png.py          # 启动图形界面
```

依赖只有 PyMuPDF，**不需要**安装 poppler / Ghostscript 等外部程序。
