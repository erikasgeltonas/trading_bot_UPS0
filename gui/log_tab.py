# gui/log_tab.py
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


class LogTab:
    """
    Programos / backtest / runner log tab.
    Rodo global logging output per thread-safe queue.
    """

    LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

    def __init__(self, parent, log_queue: queue.Queue[str]):
        self.frame = tk.Frame(parent)
        self._q = log_queue

        self._all_lines: list[str] = []
        self._max_lines = 8000

        self.var_level = tk.StringVar(value="INFO")
        self.var_search = tk.StringVar(value="")
        self.var_autoscroll = tk.BooleanVar(value=True)

        self._build_ui()
        self._poll_logs()

    # ---------------- UI ----------------

    def _build_ui(self):
        top = tk.Frame(self.frame)
        top.pack(fill="x", padx=6, pady=6)

        tk.Label(top, text="Level:").pack(side="left")
        level_box = ttk.Combobox(
            top,
            values=self.LEVELS,
            width=10,
            state="readonly",
            textvariable=self.var_level,
        )
        level_box.pack(side="left", padx=(6, 12))
        level_box.bind("<<ComboboxSelected>>", lambda e: self._refresh_view())

        tk.Label(top, text="Search:").pack(side="left")
        search_entry = tk.Entry(top, textvariable=self.var_search, width=35)
        search_entry.pack(side="left", padx=(6, 6))
        search_entry.bind("<KeyRelease>", lambda e: self._refresh_view())

        ttk.Checkbutton(
            top,
            text="Auto-scroll",
            variable=self.var_autoscroll,
        ).pack(side="left", padx=(12, 6))

        ttk.Button(top, text="Clear", command=self._clear).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="Save…", command=self._save).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="Refresh", command=self._refresh_view).pack(side="right", padx=(6, 0))

        # ---- Text area ----
        body = tk.Frame(self.frame)
        body.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self.text = tk.Text(body, wrap="none")
        self.text.pack(side="left", fill="both", expand=True)

        yscroll = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        yscroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=yscroll.set)

        xscroll = ttk.Scrollbar(self.frame, orient="horizontal", command=self.text.xview)
        xscroll.pack(fill="x", padx=6, pady=(0, 6))
        self.text.configure(xscrollcommand=xscroll.set)

        self.text.configure(state="disabled")

    # ---------------- Actions ----------------

    def _clear(self):
        self._all_lines.clear()
        self._set_text("")

    def _save(self):
        if not self._all_lines:
            messagebox.showinfo("Log", "Log is empty.")
            return

        path = filedialog.asksaveasfilename(
            title="Save log",
            defaultextension=".log",
            filetypes=[
                ("Log files", "*.log"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(self._all_lines))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save log:\n{e}")
            return

        messagebox.showinfo("Saved", f"Log saved:\n{path}")

    # ---------------- Filtering ----------------

    def _level_allowed(self, line: str) -> bool:
        parts = line.split(" | ")
        if len(parts) < 3:
            return True

        level = parts[1].strip()
        try:
            min_level = self.LEVELS.index(self.var_level.get())
            line_level = self.LEVELS.index(level) if level in self.LEVELS else 0
            return line_level >= min_level
        except Exception:
            return True

    def _matches_search(self, line: str) -> bool:
        q = self.var_search.get().strip().lower()
        if not q:
            return True
        return q in line.lower()

    def _refresh_view(self):
        visible = [
            ln
            for ln in self._all_lines
            if self._level_allowed(ln) and self._matches_search(ln)
        ]
        self._set_text("\n".join(visible))

    def _set_text(self, content: str):
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, content)
        self.text.configure(state="disabled")
        if self.var_autoscroll.get():
            self.text.see(tk.END)

    # ---------------- Polling ----------------

    def _append_lines(self, lines: list[str]):
        self._all_lines.extend(lines)
        if len(self._all_lines) > self._max_lines:
            self._all_lines = self._all_lines[-self._max_lines :]
        self._refresh_view()

    def _poll_logs(self):
        batch: list[str] = []
        try:
            while True:
                batch.append(self._q.get_nowait())
        except queue.Empty:
            pass
        except Exception:
            pass

        if batch:
            self._append_lines(batch)

        self.frame.after(150, self._poll_logs)
