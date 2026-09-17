#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 首页转 PNG 批量工具

把指定文件夹下所有 PDF 的第一页导出为 PNG，文件名与原 PDF 相同。

用法:
    图形界面:  python pdf_to_png.py
    命令行:    python pdf_to_png.py <输入文件夹> <输出文件夹> [--dpi 150] [-r] [--keep-tree]
                                    [--on-exist overwrite|skip|rename]
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
from dataclasses import dataclass, asdict
from pathlib import Path

APP_NAME = "PDF 首页转 PNG"
APP_VERSION = "1.0.0"
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

ON_EXIST_CHOICES = ("overwrite", "skip", "rename")


@dataclass
class Options:
    src: Path
    dst: Path
    dpi: int = 150
    recursive: bool = False
    keep_tree: bool = False          # 递归时在输出目录里保留子目录结构
    on_exist: str = "rename"         # overwrite / skip / rename


def find_pdfs(src: Path, recursive: bool) -> list[Path]:
    """列出待处理的 PDF，按路径排序。"""
    walker = src.rglob("*") if recursive else src.glob("*")
    return sorted(p for p in walker if p.is_file() and p.suffix.lower() == ".pdf")


def target_path(pdf: Path, opt: Options) -> Path:
    """计算 PNG 输出路径：同名，只换扩展名。"""
    out_dir = opt.dst
    if opt.recursive and opt.keep_tree:
        out_dir = opt.dst / pdf.parent.relative_to(opt.src)
    return out_dir / (pdf.stem + ".png")


def resolve_conflict(path: Path, on_exist: str) -> Path | None:
    """处理重名：覆盖返回原路径，跳过返回 None，重命名返回 name_1.png。"""
    if not path.exists():
        return path
    if on_exist == "overwrite":
        return path
    if on_exist == "skip":
        return None
    index = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def convert_one(pdf: Path, opt: Options) -> tuple[str, Path | None, str]:
    """转换单个 PDF，返回 (状态, 输出路径, 说明)，状态为 ok / skip / fail。"""
    planned = target_path(pdf, opt)
    out = resolve_conflict(planned, opt.on_exist)
    if out is None:
        return "skip", planned, "同名 PNG 已存在"

    doc = pymupdf.open(pdf)
    try:
        if doc.needs_pass and not doc.authenticate(""):
            return "fail", None, "PDF 已加密，需要密码"
        if doc.page_count < 1:
            return "fail", None, "PDF 没有任何页面"
        pix = doc.load_page(0).get_pixmap(dpi=opt.dpi)
        out.parent.mkdir(parents=True, exist_ok=True)
        pix.save(out)
    finally:
        doc.close()
    return "ok", out, ""


def run_batch(opt: Options, on_log=None, on_progress=None, cancel=None) -> dict:
    """批量转换。on_log(text, level) / on_progress(done, total) 为回调，cancel 为 Event。"""
    log = on_log or (lambda text, level="info": None)
    progress = on_progress or (lambda done, total: None)

    if pymupdf is None:
        raise RuntimeError("未安装 PyMuPDF，请先执行: pip install pymupdf")
    if not opt.src.is_dir():
        raise RuntimeError(f"输入文件夹不存在: {opt.src}")
    if not (1 <= opt.dpi <= 1200):
        raise RuntimeError("DPI 需要在 1~1200 之间")

    opt.dst.mkdir(parents=True, exist_ok=True)

    pdfs = find_pdfs(opt.src, opt.recursive)
    total = len(pdfs)
    stat = {"total": total, "ok": 0, "skip": 0, "fail": 0}
    log(f"找到 {total} 个 PDF 文件。", "info")
    progress(0, total)

    for i, pdf in enumerate(pdfs, 1):
        if cancel is not None and cancel.is_set():
            log("已取消。", "warn")
            break
        name = pdf.relative_to(opt.src)
        try:
            status, out, note = convert_one(pdf, opt)
        except Exception as exc:  # 单个文件失败不影响整体
            status, out, note = "fail", None, f"{type(exc).__name__}: {exc}"
        stat[status] += 1
        if status == "ok":
            log(f"[{i}/{total}] ✓ {name}  →  {out.name}", "ok")
        elif status == "skip":
            log(f"[{i}/{total}] – {name}  跳过：{note}", "warn")
        else:
            log(f"[{i}/{total}] ✗ {name}  失败：{note}", "error")
        progress(i, total)

    log(
        f"完成：成功 {stat['ok']} 个，跳过 {stat['skip']} 个，失败 {stat['fail']} 个。",
        "info",
    )
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

    ON_EXIST_LABELS = {
        "自动重命名（name_1.png）": "rename",
        "覆盖已有文件": "overwrite",
        "跳过已存在的": "skip",
    }
    LABEL_BY_VALUE = {v: k for k, v in ON_EXIST_LABELS.items()}

    class App(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title(f"{APP_NAME} v{APP_VERSION}")
            self.minsize(720, 520)
            self.queue: queue.Queue = queue.Queue()
            self.cancel = threading.Event()
            self.worker: threading.Thread | None = None

            self.var_src = tk.StringVar()
            self.var_dst = tk.StringVar()
            self.var_dpi = tk.StringVar(value="150")
            self.var_recursive = tk.BooleanVar(value=False)
            self.var_keep_tree = tk.BooleanVar(value=False)
            self.var_on_exist = tk.StringVar(value=LABEL_BY_VALUE["rename"])
            self.var_status = tk.StringVar(value="就绪")

            self._build_ui()
            self._load_config()
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(100, self._drain_queue)

        # ---------------- 界面 ---------------- #
        def _build_ui(self) -> None:
            pad = {"padx": 8, "pady": 6}
            self.columnconfigure(0, weight=1)
            self.rowconfigure(2, weight=1)

            frm = ttk.LabelFrame(self, text="文件夹")
            frm.grid(row=0, column=0, sticky="ew", **pad)
            frm.columnconfigure(1, weight=1)

            ttk.Label(frm, text="PDF 文件夹：").grid(row=0, column=0, sticky="w", padx=8, pady=6)
            ttk.Entry(frm, textvariable=self.var_src).grid(row=0, column=1, sticky="ew", pady=6)
            ttk.Button(frm, text="浏览…", command=self._pick_src).grid(row=0, column=2, padx=8)

            ttk.Label(frm, text="输出文件夹：").grid(row=1, column=0, sticky="w", padx=8, pady=6)
            ttk.Entry(frm, textvariable=self.var_dst).grid(row=1, column=1, sticky="ew", pady=6)
            ttk.Button(frm, text="浏览…", command=self._pick_dst).grid(row=1, column=2, padx=8)

            opts = ttk.LabelFrame(self, text="选项")
            opts.grid(row=1, column=0, sticky="ew", **pad)

            ttk.Label(opts, text="分辨率 DPI：").grid(row=0, column=0, sticky="w", padx=8, pady=6)
            ttk.Combobox(
                opts,
                textvariable=self.var_dpi,
                values=("72", "96", "150", "200", "300", "600"),
                width=8,
            ).grid(row=0, column=1, sticky="w", pady=6)

            ttk.Label(opts, text="同名文件：").grid(row=0, column=2, sticky="w", padx=(20, 4))
            ttk.Combobox(
                opts,
                textvariable=self.var_on_exist,
                values=tuple(ON_EXIST_LABELS),
                state="readonly",
                width=22,
            ).grid(row=0, column=3, sticky="w")

            ttk.Checkbutton(
                opts,
                text="包含子文件夹",
                variable=self.var_recursive,
                command=self._sync_tree_state,
            ).grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))
            self.chk_tree = ttk.Checkbutton(
                opts, text="输出时保留子目录结构", variable=self.var_keep_tree
            )
            self.chk_tree.grid(row=1, column=2, columnspan=2, sticky="w", padx=(20, 8), pady=(0, 8))
            self._sync_tree_state()

            logfrm = ttk.LabelFrame(self, text="日志")
            logfrm.grid(row=2, column=0, sticky="nsew", **pad)
            logfrm.columnconfigure(0, weight=1)
            logfrm.rowconfigure(0, weight=1)

            self.txt = tk.Text(logfrm, height=14, wrap="none", state="disabled")
            self.txt.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
            bar = ttk.Scrollbar(logfrm, orient="vertical", command=self.txt.yview)
            bar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
            self.txt.configure(yscrollcommand=bar.set)
            self.txt.tag_configure("ok", foreground="#1a7f37")
            self.txt.tag_configure("warn", foreground="#9a6700")
            self.txt.tag_configure("error", foreground="#cf222e")
            self.txt.tag_configure("info", foreground="#0550ae")

            bottom = ttk.Frame(self)
            bottom.grid(row=3, column=0, sticky="ew", **pad)
            bottom.columnconfigure(0, weight=1)

            self.progress = ttk.Progressbar(bottom, mode="determinate")
            self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
            ttk.Label(bottom, textvariable=self.var_status, width=28).grid(row=0, column=1)

            self.btn_start = ttk.Button(bottom, text="开始转换", command=self._start)
            self.btn_start.grid(row=0, column=2, padx=4)
            self.btn_stop = ttk.Button(bottom, text="停止", command=self._stop, state="disabled")
            self.btn_stop.grid(row=0, column=3, padx=4)
            self.btn_open = ttk.Button(bottom, text="打开输出目录", command=self._open_dst)
            self.btn_open.grid(row=0, column=4, padx=4)

        def _sync_tree_state(self) -> None:
            self.chk_tree.configure(state="normal" if self.var_recursive.get() else "disabled")

        # ---------------- 交互 ---------------- #
        def _pick_src(self) -> None:
            path = filedialog.askdirectory(title="选择包含 PDF 的文件夹", initialdir=self.var_src.get() or None)
            if path:
                self.var_src.set(path)
                if not self.var_dst.get():
                    self.var_dst.set(str(Path(path) / "png"))

        def _pick_dst(self) -> None:
            path = filedialog.askdirectory(title="选择 PNG 输出文件夹", initialdir=self.var_dst.get() or None)
            if path:
                self.var_dst.set(path)

        def _open_dst(self) -> None:
            dst = Path(self.var_dst.get()).expanduser()
            if dst.is_dir():
                open_in_file_manager(dst)
            else:
                messagebox.showinfo(APP_NAME, "输出文件夹还不存在。")

        def _log(self, text: str, level: str = "info") -> None:
            self.txt.configure(state="normal")
            self.txt.insert("end", text + "\n", level)
            self.txt.see("end")
            self.txt.configure(state="disabled")

        def _start(self) -> None:
            if self.worker and self.worker.is_alive():
                return
            src = Path(self.var_src.get().strip()).expanduser()
            dst_raw = self.var_dst.get().strip()
            if not self.var_src.get().strip() or not src.is_dir():
                messagebox.showerror(APP_NAME, "请选择一个存在的 PDF 文件夹。")
                return
            if not dst_raw:
                messagebox.showerror(APP_NAME, "请选择输出文件夹。")
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
                src=src,
                dst=Path(dst_raw).expanduser(),
                dpi=dpi,
                recursive=self.var_recursive.get(),
                keep_tree=self.var_keep_tree.get(),
                on_exist=ON_EXIST_LABELS[self.var_on_exist.get()],
            )
            self._save_config()

            self.txt.configure(state="normal")
            self.txt.delete("1.0", "end")
            self.txt.configure(state="disabled")
            self.progress.configure(value=0, maximum=1)
            self.cancel.clear()
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.var_status.set("处理中…")

            def work() -> None:
                try:
                    run_batch(
                        opt,
                        on_log=lambda t, lv="info": self.queue.put(("log", t, lv)),
                        on_progress=lambda d, t: self.queue.put(("progress", d, t)),
                        cancel=self.cancel,
                    )
                except Exception as exc:
                    self.queue.put(("log", f"出错：{exc}", "error"))
                    self.queue.put(("log", traceback.format_exc(), "error"))
                finally:
                    self.queue.put(("done", None, None))

            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()

        def _stop(self) -> None:
            self.cancel.set()
            self.var_status.set("正在停止…")

        def _drain_queue(self) -> None:
            try:
                while True:
                    kind, a, b = self.queue.get_nowait()
                    if kind == "log":
                        self._log(a, b)
                    elif kind == "progress":
                        self.progress.configure(maximum=max(b, 1), value=a)
                        self.var_status.set(f"{a} / {b}")
                    elif kind == "done":
                        self.btn_start.configure(state="normal")
                        self.btn_stop.configure(state="disabled")
                        self.var_status.set("完成")
            except queue.Empty:
                pass
            self.after(100, self._drain_queue)

        # ---------------- 配置记忆 ---------------- #
        def _load_config(self) -> None:
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                return
            self.var_src.set(data.get("src", ""))
            self.var_dst.set(data.get("dst", ""))
            self.var_dpi.set(str(data.get("dpi", 150)))
            self.var_recursive.set(bool(data.get("recursive", False)))
            self.var_keep_tree.set(bool(data.get("keep_tree", False)))
            self.var_on_exist.set(LABEL_BY_VALUE.get(data.get("on_exist", "rename"), LABEL_BY_VALUE["rename"]))
            self._sync_tree_state()

        def _save_config(self) -> None:
            data = {
                "src": self.var_src.get(),
                "dst": self.var_dst.get(),
                "dpi": self.var_dpi.get(),
                "recursive": self.var_recursive.get(),
                "keep_tree": self.var_keep_tree.get(),
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

    parser = argparse.ArgumentParser(description="把文件夹下所有 PDF 的第一页导出为同名 PNG")
    parser.add_argument("src", help="包含 PDF 的输入文件夹")
    parser.add_argument("dst", help="PNG 输出文件夹")
    parser.add_argument("--dpi", type=int, default=150, help="输出分辨率，默认 150")
    parser.add_argument("-r", "--recursive", action="store_true", help="递归处理子文件夹")
    parser.add_argument("--keep-tree", action="store_true", help="递归时保留子目录结构")
    parser.add_argument(
        "--on-exist", choices=ON_EXIST_CHOICES, default="rename", help="同名 PNG 的处理方式"
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args(argv)

    opt = Options(
        src=Path(args.src).expanduser(),
        dst=Path(args.dst).expanduser(),
        dpi=args.dpi,
        recursive=args.recursive,
        keep_tree=args.keep_tree,
        on_exist=args.on_exist,
    )
    try:
        stat = run_batch(opt, on_log=lambda t, lv="info": print(t))
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    return 1 if stat["fail"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
