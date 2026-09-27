from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


ROOT = Path(__file__).resolve().parent


class SubtitleApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ja2zh-subtitle v0.3.0")
        self.root.geometry("820x600")
        self.messages: queue.Queue[str | None] = queue.Queue()

        self.input_path = tk.StringVar()
        self.subtitle_path = tk.StringVar()
        self.output_path = tk.StringVar(value=str(ROOT / "output"))
        self.preset = tk.StringVar(value="auto")
        self.japanese_only = tk.BooleanVar(value=False)
        self.subtitle_only = tk.BooleanVar(value=False)
        self.no_polish = tk.BooleanVar(value=False)
        self.offline = tk.BooleanVar(value=False)
        self.recursive = tk.BooleanVar(value=False)

        frame = ttk.Frame(root, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        self._path_row(frame, 0, "视频或目录", self.input_path, self._pick_video, self._pick_directory)
        self._path_row(frame, 1, "现有字幕（可选）", self.subtitle_path, self._pick_subtitle)
        self._path_row(frame, 2, "输出目录", self.output_path, self._pick_output)

        ttk.Label(frame, text="模型档位").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Combobox(
            frame,
            textvariable=self.preset,
            values=("auto", "lite", "balanced", "quality"),
            state="readonly",
            width=16,
        ).grid(row=3, column=1, sticky="w", pady=6)

        options = ttk.Frame(frame)
        options.grid(row=4, column=0, columnspan=4, sticky="w", pady=6)
        for text, variable in (
            ("只处理日语，不翻译", self.japanese_only),
            ("只生成字幕，不烧录", self.subtitle_only),
            ("跳过 Qwen 润色", self.no_polish),
            ("强制离线", self.offline),
            ("递归扫描目录", self.recursive),
        ):
            ttk.Checkbutton(options, text=text, variable=variable).pack(side="left", padx=(0, 12))

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 10))
        self.run_button = ttk.Button(buttons, text="开始处理", command=self.start)
        self.run_button.pack(side="left")
        ttk.Button(buttons, text="环境检查", command=self.doctor).pack(side="left", padx=8)
        ttk.Button(buttons, text="清空日志", command=self.clear_log).pack(side="left")

        self.log = tk.Text(frame, wrap="word", height=24)
        self.log.grid(row=6, column=0, columnspan=4, sticky="nsew")
        frame.rowconfigure(6, weight=1)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=6, column=4, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

    def _path_row(self, parent, row, label, variable, primary, secondary=None) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8)
        ttk.Button(parent, text="选择", command=primary).grid(row=row, column=2, pady=6)
        if secondary:
            ttk.Button(parent, text="选择目录", command=secondary).grid(row=row, column=3, padx=(6, 0), pady=6)

    def _pick_video(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("视频文件", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.ts"), ("所有文件", "*.*")]
        )
        if path:
            self.input_path.set(path)

    def _pick_directory(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.input_path.set(path)

    def _pick_subtitle(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("字幕文件", "*.srt *.ass")])
        if path:
            self.subtitle_path.set(path)

    def _pick_output(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.output_path.set(path)

    def clear_log(self) -> None:
        self.log.delete("1.0", "end")

    def doctor(self) -> None:
        self._launch([sys.executable, str(ROOT / "main.py"), "--doctor"])

    def start(self) -> None:
        source = self.input_path.get().strip()
        if not source:
            messagebox.showerror("缺少输入", "请选择视频文件或目录。")
            return
        command = [sys.executable, str(ROOT / "main.py"), source]
        command += ["--preset", self.preset.get(), "--output-dir", self.output_path.get().strip()]
        if self.subtitle_path.get().strip():
            if Path(source).is_dir():
                messagebox.showerror("参数冲突", "重新烧录字幕时必须选择单个视频。")
                return
            command += ["--burn-subtitle", self.subtitle_path.get().strip()]
        else:
            if self.japanese_only.get():
                command.append("--ja-only")
            if self.subtitle_only.get():
                command.append("--subtitle-only")
            if self.no_polish.get():
                command.append("--no-polish")
            if self.offline.get():
                command.append("--offline")
            if self.recursive.get():
                command.append("--recursive")
        self._launch(command)

    def _launch(self, command: list[str]) -> None:
        self.run_button.configure(state="disabled")
        self.log.insert("end", "> " + " ".join(command) + "\n")
        self.log.see("end")

        def worker() -> None:
            environment = os.environ.copy()
            environment["PYTHONUTF8"] = "1"
            try:
                process = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                )
                assert process.stdout is not None
                for line in process.stdout:
                    self.messages.put(line)
                code = process.wait()
                self.messages.put(f"\n进程结束，退出码：{code}\n")
            except Exception as exc:
                self.messages.put(f"\n启动失败：{exc}\n")
            finally:
                self.messages.put(None)

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._drain_messages)

    def _drain_messages(self) -> None:
        finished = False
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            if message is None:
                finished = True
            else:
                self.log.insert("end", message)
                self.log.see("end")
        if finished:
            self.run_button.configure(state="normal")
        else:
            self.root.after(100, self._drain_messages)


def main() -> None:
    root = tk.Tk()
    SubtitleApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
