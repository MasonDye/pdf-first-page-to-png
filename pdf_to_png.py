#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 首页转图片批量工具

扫描所选文件夹（含全部子文件夹）里的每一个 PDF，把第一页导出为 PNG 或 JPG，
**直接保存在该 PDF 自己所在的文件夹里**，文件名与 PDF 相同。
目标文件已存在时不覆盖，自动追加 (1)、(2) 这样的序号。

用法:
    图形界面:  python pdf_to_png.py
    命令行:    python pdf_to_png.py <PDF文件夹> [-f png|jpg] [--dpi 150]
                                    [--on-exist rename|skip|overwrite]
                                    [-o 另存到别处] [--no-recursive] [--keep-tree]
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

APP_NAME = "PDF 首页转图片"
APP_VERSION = "2.1.0"
CONFIG_PATH = Path.home() / ".pdf_first_page_png.json"

try:
    import pymupdf  # PyMuPDF >= 1.24
except ImportError:  # pragma: no cover - 兼容旧版包名
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None


# --------------------------------------------------------------------------- #
# 核心转换逻辑（与界面无关，命令行同样复用）
# --------------------------------------------------------------------------- #

ON_EXIST_CHOICES = ("rename", "skip", "overwrite")

# 输出格式 -> 扩展名。JPG 固定用最高质量：MuPDF 在 quality=100 时不做色度抽样
# （4:4:4），与 Pillow 的 quality=100/subsampling=0 逐像素一致，肉眼无损。
FORMATS = {"png": ".png", "jpg": ".jpg"}
DEFAULT_JPG_QUALITY = 100

# 单个文件的处理结果
ST_PENDING = "待提取"
ST_RUNNING = "提取中…"
ST_DONE = "提取完成"
ST_SKIP = "已跳过"
ST_FAIL = "失败"


@dataclass
class Options:
    src: Path
    dst: Path | None = None      # None = 存回 PDF 所在的文件夹（默认行为）
    fmt: str = "png"             # png / jpg
    dpi: int = 150
    jpg_quality: int = DEFAULT_JPG_QUALITY
    recursive: bool = True       # 默认连子文件夹一起处理
    keep_tree: bool = False      # 仅在 dst 不为 None 时有意义
    on_exist: str = "rename"     # rename / skip / overwrite


def fs_path(path: Path) -> str:
    """转成可传给底层库的路径字符串。

    Windows 上路径超过 260 字符会打不开，这里加 \\\\?\\ 前缀绕过限制
    （电子书库那种 `【xxxx】书名_作者` 的深层目录很容易超长）。
    """
    text = str(path)
    if sys.platform != "win32" or len(text) < 240 or text.startswith("\\\\?\\"):
        return text
    full = os.path.abspath(text)
    if full.startswith("\\\\"):            # UNC: \\server\share -> \\?\UNC\server\share
        return "\\\\?\\UNC\\" + full[2:]
    return "\\\\?\\" + full


def scan_pdfs(src: Path, recursive: bool = True, cancel=None) -> Iterator[Path]:
    """逐个产出待处理的 PDF，按目录和文件名排序。边扫边给，方便界面即时显示。"""
    if not recursive:
        for item in sorted(src.iterdir(), key=lambda p: p.name.lower()):
            if item.is_file() and item.suffix.lower() == ".pdf":
                yield item
        return

    for root, dirs, files in os.walk(src):
        if cancel is not None and cancel.is_set():
            return
        dirs.sort(key=str.lower)
        for name in sorted(files, key=str.lower):
            if name.lower().endswith(".pdf"):
                yield Path(root) / name


def target_path(pdf: Path, opt: Options) -> Path:
    """图片输出路径：默认与 PDF 同目录、同名，只换扩展名。"""
    suffix = FORMATS[opt.fmt]
    if opt.dst is None:
        return pdf.with_suffix(suffix)
    if opt.recursive and opt.keep_tree:
        return opt.dst / pdf.parent.relative_to(opt.src) / (pdf.stem + suffix)
    return opt.dst / (pdf.stem + suffix)


def resolve_conflict(path: Path, on_exist: str) -> Path | None:
    """处理重名。

    默认不覆盖已有文件，按资源管理器的习惯追加序号：
    ``封面.png`` -> ``封面 (1).png`` -> ``封面 (2).png``。
    覆盖返回原路径，跳过返回 None。
    """
    if not path.exists():
        return path
    if on_exist == "overwrite":
        return path
    if on_exist == "skip":
        return None
    index = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def convert_one(pdf: Path, opt: Options) -> tuple[str, Path | None, str]:
    """转换单个 PDF，返回 (状态, 输出路径, 说明)。"""
    planned = target_path(pdf, opt)
    out = resolve_conflict(planned, opt.on_exist)
    if out is None:
        return ST_SKIP, planned, f"同名 {opt.fmt.upper()} 已存在"

    doc = pymupdf.open(fs_path(pdf))
    try:
        if doc.needs_pass and not doc.authenticate(""):
            return ST_FAIL, None, "PDF 已加密，需要密码"
        if doc.page_count < 1:
            return ST_FAIL, None, "PDF 没有任何页面"
        pix = doc.load_page(0).get_pixmap(dpi=opt.dpi)
        if not out.parent.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
        if opt.fmt == "jpg":
            pix.save(fs_path(out), jpg_quality=opt.jpg_quality)
        else:
            pix.save(fs_path(out))
    finally:
        doc.close()
    note = "" if out == planned else f"已有同名文件，另存为 {out.name}"
    return ST_DONE, out, note


def convert_all(
    pdfs: list[Path],
    opt: Options,
    on_item: Callable[[int, Path, str, Path | None, str], None] | None = None,
    cancel=None,
) -> dict:
    """按列表逐个转换。on_item(序号, pdf, 状态, 输出路径, 说明) 在每个文件前后各调一次。"""
    if pymupdf is None:
        raise RuntimeError("未安装 PyMuPDF，请先执行: pip install pymupdf")
    report = on_item or (lambda *a: None)

    stat = {"total": len(pdfs), ST_DONE: 0, ST_SKIP: 0, ST_FAIL: 0, "cancelled": False}
    for index, pdf in enumerate(pdfs):
        if cancel is not None and cancel.is_set():
            stat["cancelled"] = True
            break
        report(index, pdf, ST_RUNNING, None, "")
        try:
            status, out, note = convert_one(pdf, opt)
        except Exception as exc:                      # 单个文件出错不影响整批
            status, out, note = ST_FAIL, None, f"{type(exc).__name__}: {exc}"
        stat[status] += 1
        report(index, pdf, status, out, note)
    return stat


def open_in_file_manager(path: Path) -> None:
    """在系统文件管理器中打开目录。"""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 图形界面
# --------------------------------------------------------------------------- #

def launch_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    if sys.platform == "win32":  # 高分屏下文字不发虚
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    FORMAT_LABELS = {"PNG（无损）": "png", "JPG（最高画质，无色度抽样）": "jpg"}
    FORMAT_BY_VALUE = {v: k for k, v in FORMAT_LABELS.items()}
    ON_EXIST_LABELS = {
        "自动加序号（封面 (1).png）": "rename",
        "跳过已存在的": "skip",
        "覆盖已有文件": "overwrite",
    }
    LABEL_BY_VALUE = {v: k for k, v in ON_EXIST_LABELS.items()}
    STATUS_TAG = {
        ST_PENDING: "pending",
        ST_RUNNING: "running",
        ST_DONE: "done",
        ST_SKIP: "skip",
        ST_FAIL: "fail",
    }

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title(f"{APP_NAME} v{APP_VERSION}")
            self.minsize(900, 560)

            self.queue: queue.Queue = queue.Queue()
            self.cancel = threading.Event()
            self.worker: threading.Thread | None = None
            self.scanner: threading.Thread | None = None
            self.pdfs: list[Path] = []
            self.counts = {ST_PENDING: 0, ST_DONE: 0, ST_SKIP: 0, ST_FAIL: 0}

            self.var_src = tk.StringVar()
            self.var_fmt = tk.StringVar(value=FORMAT_BY_VALUE["png"])
            self.var_dpi = tk.StringVar(value="150")
            self.var_on_exist = tk.StringVar(value=LABEL_BY_VALUE["rename"])
            self.var_summary = tk.StringVar(value="尚未选择文件夹")
            self.var_status = tk.StringVar(value="就绪")

            self._build_ui()
            self._load_config()
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(80, self._drain_queue)
            if self.var_src.get().strip():
                self.after(200, self._rescan)

        # ---------------- 界面 ---------------- #
        def _build_ui(self) -> None:
            pad = {"padx": 8, "pady": 6}
            self.columnconfigure(0, weight=1)
            self.rowconfigure(2, weight=1)

            frm = ttk.LabelFrame(self, text="PDF 文件夹")
            frm.grid(row=0, column=0, sticky="ew", **pad)
            frm.columnconfigure(0, weight=1)

            row = ttk.Frame(frm)
            row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))
            row.columnconfigure(0, weight=1)
            entry = ttk.Entry(row, textvariable=self.var_src)
            entry.grid(row=0, column=0, sticky="ew")
            entry.bind("<Return>", lambda _e: self._rescan())
            ttk.Button(row, text="浏览…", command=self._pick_src).grid(row=0, column=1, padx=(8, 0))
            ttk.Button(row, text="重新扫描", command=self._rescan).grid(row=0, column=2, padx=(6, 0))

            ttk.Label(
                frm,
                text="封面图片会直接存回每个 PDF 所在的文件夹，文件名与 PDF 相同；所有子文件夹一并处理。",
                foreground="#555555",
            ).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 8))

            opts = ttk.LabelFrame(self, text="选项")
            opts.grid(row=1, column=0, sticky="ew", **pad)

            ttk.Label(opts, text="图片格式：").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
            ttk.Combobox(
                opts,
                textvariable=self.var_fmt,
                values=tuple(FORMAT_LABELS),
                state="readonly",
                width=26,
            ).grid(row=0, column=1, sticky="w", pady=(8, 4))
            ttk.Label(opts, text="分辨率 DPI：").grid(row=0, column=2, sticky="w", padx=(24, 4))
            ttk.Combobox(
                opts,
                textvariable=self.var_dpi,
                values=("72", "96", "150", "200", "300", "600"),
                width=8,
            ).grid(row=0, column=3, sticky="w")

            ttk.Label(opts, text="已有同名文件：").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
            ttk.Combobox(
                opts,
                textvariable=self.var_on_exist,
                values=tuple(ON_EXIST_LABELS),
                state="readonly",
                width=26,
            ).grid(row=1, column=1, sticky="w", pady=(0, 8))
            ttk.Label(
                opts,
                text="（默认不覆盖，自动存成「封面 (1).png」）",
                foreground="#555555",
            ).grid(row=1, column=2, columnspan=2, sticky="w", padx=(24, 8), pady=(0, 8))

            listfrm = ttk.LabelFrame(self, text="文件列表")
            listfrm.grid(row=2, column=0, sticky="nsew", **pad)
            listfrm.columnconfigure(0, weight=1)
            listfrm.rowconfigure(1, weight=1)

            ttk.Label(listfrm, textvariable=self.var_summary).grid(
                row=0, column=0, sticky="w", padx=10, pady=(6, 2)
            )

            self.tree = ttk.Treeview(
                listfrm, columns=("status", "folder"), show="tree headings", selectmode="browse"
            )
            self.tree.heading("#0", text="PDF 文件")
            self.tree.heading("status", text="状态")
            self.tree.heading("folder", text="所在文件夹")
            self.tree.column("#0", width=300, minwidth=160, stretch=False)
            self.tree.column("status", width=150, minwidth=90, anchor="w", stretch=False)
            self.tree.column("folder", width=430, minwidth=200)
            self.tree.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=(0, 8))
            self.tree.tag_configure("pending", foreground="#57606a")
            self.tree.tag_configure("running", foreground="#0550ae")
            self.tree.tag_configure("done", foreground="#1a7f37")
            self.tree.tag_configure("skip", foreground="#9a6700")
            self.tree.tag_configure("fail", foreground="#cf222e")
            self.tree.bind("<Double-1>", self._open_selected)

            vbar = ttk.Scrollbar(listfrm, orient="vertical", command=self.tree.yview)
            vbar.grid(row=1, column=1, sticky="ns", padx=(0, 8), pady=(0, 8))
            hbar = ttk.Scrollbar(listfrm, orient="horizontal", command=self.tree.xview)
            hbar.grid(row=2, column=0, sticky="ew", padx=(8, 0), pady=(0, 6))
            self.tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

            bottom = ttk.Frame(self)
            bottom.grid(row=3, column=0, sticky="ew", **pad)
            bottom.columnconfigure(0, weight=1)
            self.progress = ttk.Progressbar(bottom, mode="determinate")
            self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
            ttk.Label(bottom, textvariable=self.var_status, width=30).grid(row=0, column=1)
            self.btn_start = ttk.Button(bottom, text="开始转换", command=self._start)
            self.btn_start.grid(row=0, column=2, padx=4)
            self.btn_stop = ttk.Button(bottom, text="停止", command=self._stop, state="disabled")
            self.btn_stop.grid(row=0, column=3, padx=4)
            ttk.Button(bottom, text="打开文件夹", command=self._open_src).grid(row=0, column=4, padx=4)

        # ---------------- 扫描 ---------------- #
        def _pick_src(self) -> None:
            path = filedialog.askdirectory(
                title="选择包含 PDF 的文件夹（含全部子文件夹）",
                initialdir=self.var_src.get() or None,
            )
            if path:
                self.var_src.set(path)
                self._rescan()

        def _rescan(self) -> None:
            if self.worker and self.worker.is_alive():
                return
            if self.scanner and self.scanner.is_alive():
                self.cancel.set()
                self.scanner.join(timeout=2)
            raw = self.var_src.get().strip()
            if not raw:
                return
            src = Path(raw).expanduser()
            if not src.is_dir():
                messagebox.showerror(APP_NAME, f"文件夹不存在：\n{src}")
                return

            self.tree.delete(*self.tree.get_children())
            self.pdfs = []
            self.counts = {ST_PENDING: 0, ST_DONE: 0, ST_SKIP: 0, ST_FAIL: 0}
            self.progress.configure(value=0, maximum=1)
            self.var_summary.set("正在扫描…")
            self.var_status.set("扫描中…")
            self.cancel = threading.Event()
            self._save_config()

            def work(cancel=self.cancel) -> None:
                batch: list[Path] = []
                try:
                    for pdf in scan_pdfs(src, recursive=True, cancel=cancel):
                        batch.append(pdf)
                        if len(batch) >= 200:
                            self.queue.put(("add", batch, None))
                            batch = []
                    if batch:
                        self.queue.put(("add", batch, None))
                except Exception as exc:
                    self.queue.put(("error", f"扫描失败：{exc}", None))
                finally:
                    self.queue.put(("scanned", str(src), None))

            self.scanner = threading.Thread(target=work, daemon=True)
            self.scanner.start()

        def _add_rows(self, pdfs: list[Path]) -> None:
            src = Path(self.var_src.get().strip()).expanduser()
            for pdf in pdfs:
                index = len(self.pdfs)
                self.pdfs.append(pdf)
                try:
                    folder = str(pdf.parent.relative_to(src))
                except ValueError:
                    folder = str(pdf.parent)
                self.tree.insert(
                    "",
                    "end",
                    iid=f"i{index}",
                    text=pdf.name,
                    values=(ST_PENDING, folder if folder != "." else "（根目录）"),
                    tags=("pending",),
                )
            self.counts[ST_PENDING] = len(self.pdfs) - (
                self.counts[ST_DONE] + self.counts[ST_SKIP] + self.counts[ST_FAIL]
            )
            self._refresh_summary()

        def _refresh_summary(self) -> None:
            c = self.counts
            self.var_summary.set(
                f"共 {len(self.pdfs)} 个 PDF　|　待提取 {c[ST_PENDING]}　"
                f"提取完成 {c[ST_DONE]}　已跳过 {c[ST_SKIP]}　失败 {c[ST_FAIL]}"
            )

        # ---------------- 转换 ---------------- #
        def _start(self) -> None:
            if self.worker and self.worker.is_alive():
                return
            if self.scanner and self.scanner.is_alive():
                messagebox.showinfo(APP_NAME, "正在扫描文件，请稍候…")
                return
            if not self.pdfs:
                messagebox.showinfo(APP_NAME, "列表里没有 PDF，请先选择文件夹。")
                return
            try:
                dpi = int(float(self.var_dpi.get()))
            except ValueError:
                messagebox.showerror(APP_NAME, "DPI 必须是数字。")
                return
            if not 1 <= dpi <= 1200:
                messagebox.showerror(APP_NAME, "DPI 需要在 1~1200 之间。")
                return

            opt = Options(
                src=Path(self.var_src.get().strip()).expanduser(),
                dst=None,                                  # 存回 PDF 所在目录
                fmt=FORMAT_LABELS[self.var_fmt.get()],
                dpi=dpi,
                recursive=True,
                on_exist=ON_EXIST_LABELS[self.var_on_exist.get()],
            )
            self._save_config()

            # 重置所有行的状态，允许重复运行
            for index in range(len(self.pdfs)):
                self.tree.item(f"i{index}", values=(ST_PENDING, self.tree.set(f"i{index}", "folder")),
                               tags=("pending",))
            self.counts = {ST_PENDING: len(self.pdfs), ST_DONE: 0, ST_SKIP: 0, ST_FAIL: 0}
            self._refresh_summary()
            self.progress.configure(value=0, maximum=len(self.pdfs))
            self.cancel = threading.Event()
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.var_status.set(f"0 / {len(self.pdfs)}")

            pdfs = list(self.pdfs)

            def work(cancel=self.cancel) -> None:
                stat = None
                try:
                    stat = convert_all(
                        pdfs,
                        opt,
                        on_item=lambda i, p, st, out, note: self.queue.put(("item", i, (st, note))),
                        cancel=cancel,
                    )
                except Exception as exc:
                    self.queue.put(("error", f"出错：{exc}", None))
                    self.queue.put(("error", traceback.format_exc(), None))
                finally:
                    self.queue.put(("done", stat, None))

            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()

        def _stop(self) -> None:
            self.cancel.set()
            self.var_status.set("正在停止…")

        def _update_item(self, index: int, status: str, note: str) -> None:
            iid = f"i{index}"
            if not self.tree.exists(iid):
                return
            text = status if not note else f"{status}：{note}"
            self.tree.set(iid, "status", text)
            self.tree.item(iid, tags=(STATUS_TAG.get(status, "pending"),))
            if status == ST_RUNNING:
                self.tree.see(iid)
                return
            if status in self.counts:
                self.counts[status] += 1
                self.counts[ST_PENDING] = max(self.counts[ST_PENDING] - 1, 0)
            done = self.counts[ST_DONE] + self.counts[ST_SKIP] + self.counts[ST_FAIL]
            self.progress.configure(value=done)
            self.var_status.set(f"{done} / {len(self.pdfs)}")
            self._refresh_summary()

        # ---------------- 杂项 ---------------- #
        def _open_src(self) -> None:
            src = Path(self.var_src.get().strip()).expanduser()
            if src.is_dir():
                open_in_file_manager(src)
            else:
                messagebox.showinfo(APP_NAME, "请先选择一个存在的文件夹。")

        def _open_selected(self, _event=None) -> None:
            sel = self.tree.selection()
            if not sel:
                return
            index = int(sel[0][1:])
            if 0 <= index < len(self.pdfs):
                open_in_file_manager(self.pdfs[index].parent)

        def _drain_queue(self) -> None:
            pending_items: list[tuple[int, str, str]] = []
            errors: list[str] = []
            scanned = False
            finished = False
            stat = None
            try:
                while True:
                    kind, a, b = self.queue.get_nowait()
                    if kind == "add":
                        self._add_rows(a)
                    elif kind == "item":
                        pending_items.append((a, b[0], b[1]))
                    elif kind == "scanned":
                        scanned = True
                    elif kind == "error":
                        errors.append(a)
                    elif kind == "done":
                        finished, stat = True, a
            except queue.Empty:
                pass

            # 条目状态先落地，最后再写汇总文字，否则会被 "x / y" 覆盖
            for index, status, note in pending_items:
                self._update_item(index, status, note)

            if scanned:
                self.var_status.set("就绪")
                if not self.pdfs:
                    self.var_summary.set("这个文件夹（含子文件夹）里没有找到 PDF 文件")
                else:
                    self._refresh_summary()
            if finished:
                self.btn_start.configure(state="normal")
                self.btn_stop.configure(state="disabled")
                c = self.counts
                head = "已停止" if (stat and stat.get("cancelled")) else "完成"
                self.var_status.set(
                    f"{head}　成功 {c[ST_DONE]}　跳过 {c[ST_SKIP]}　失败 {c[ST_FAIL]}"
                )
            for message in errors:
                messagebox.showerror(APP_NAME, message)
            self.after(80, self._drain_queue)

        def _load_config(self) -> None:
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                return
            self.var_src.set(data.get("src", ""))
            self.var_fmt.set(FORMAT_BY_VALUE.get(data.get("fmt", "png"), FORMAT_BY_VALUE["png"]))
            self.var_dpi.set(str(data.get("dpi", 150)))
            self.var_on_exist.set(
                LABEL_BY_VALUE.get(data.get("on_exist", "rename"), LABEL_BY_VALUE["rename"])
            )

        def _save_config(self) -> None:
            data = {
                "src": self.var_src.get(),
                "fmt": FORMAT_LABELS[self.var_fmt.get()],
                "dpi": self.var_dpi.get(),
                "on_exist": ON_EXIST_LABELS[self.var_on_exist.get()],
            }
            try:
                CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

        def _on_close(self) -> None:
            self.cancel.set()
            self._save_config()
            self.destroy()

    if pymupdf is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, "未安装 PyMuPDF，请先执行:\n\npip install pymupdf")
        return 1

    App().mainloop()
    return 0


# --------------------------------------------------------------------------- #
# 命令行入口
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    if not argv:
        return launch_gui()

    parser = argparse.ArgumentParser(
        description="把文件夹（含子文件夹）下每个 PDF 的第一页导出为同名图片，默认存回 PDF 所在目录"
    )
    parser.add_argument("src", help="包含 PDF 的文件夹")
    parser.add_argument(
        "-f", "--format", choices=tuple(FORMATS), default="png", help="输出格式，默认 png"
    )
    parser.add_argument(
        "-o", "--out", default=None, help="另存到指定文件夹（不给则存回每个 PDF 自己的目录）"
    )
    parser.add_argument("--dpi", type=int, default=150, help="输出分辨率，默认 150")
    parser.add_argument(
        "--jpg-quality",
        type=int,
        default=DEFAULT_JPG_QUALITY,
        help=f"JPG 质量 1-100，默认 {DEFAULT_JPG_QUALITY}（最高画质，无色度抽样）",
    )
    parser.add_argument("--no-recursive", action="store_true", help="只处理顶层，不进子文件夹")
    parser.add_argument("--keep-tree", action="store_true", help="配合 -o：保留子目录结构")
    parser.add_argument(
        "--on-exist",
        choices=ON_EXIST_CHOICES,
        default="rename",
        help="已有同名文件时：rename 自动加 (1)（默认）/ skip 跳过 / overwrite 覆盖",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args(argv)

    opt = Options(
        src=Path(args.src).expanduser(),
        dst=Path(args.out).expanduser() if args.out else None,
        fmt=args.format,
        dpi=args.dpi,
        jpg_quality=args.jpg_quality,
        recursive=not args.no_recursive,
        keep_tree=args.keep_tree,
        on_exist=args.on_exist,
    )
    if not opt.src.is_dir():
        print(f"错误：文件夹不存在: {opt.src}", file=sys.stderr)
        return 2
    if not 1 <= opt.dpi <= 1200:
        print("错误：DPI 需要在 1~1200 之间", file=sys.stderr)
        return 2
    if not 1 <= opt.jpg_quality <= 100:
        print("错误：JPG 质量需要在 1~100 之间", file=sys.stderr)
        return 2
    if opt.dst is not None:
        opt.dst.mkdir(parents=True, exist_ok=True)

    pdfs = list(scan_pdfs(opt.src, recursive=opt.recursive))
    print(f"找到 {len(pdfs)} 个 PDF 文件，输出格式 {opt.fmt.upper()}。")

    def report(index: int, pdf: Path, status: str, out: Path | None, note: str) -> None:
        if status == ST_RUNNING:
            return
        mark = {ST_DONE: "✓", ST_SKIP: "–", ST_FAIL: "✗"}[status]
        tail = f"  →  {out.name}" if status == ST_DONE and out else ""
        if note and status != ST_DONE:
            tail = f"  {note}"
        print(f"[{index + 1}/{len(pdfs)}] {mark} {pdf.name}{tail}")

    try:
        stat = convert_all(pdfs, opt, on_item=report)
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(
        f"完成：成功 {stat[ST_DONE]} 个，跳过 {stat[ST_SKIP]} 个，失败 {stat[ST_FAIL]} 个。"
    )
    return 1 if stat[ST_FAIL] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
