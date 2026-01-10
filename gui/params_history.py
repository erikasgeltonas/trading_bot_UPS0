# gui/params_history.py
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from bot.merge_history import merge_finam_files
from bot.binance_downloader import download_binance_klines
from bybit_downloader import download_bybit_to_finam_txt


class ParamsHistoryMixin:
    """
    Iškelta istorijos (file IO) logika iš ParamsTab:
    - browse history file
    - merge finam files
    - download BTC from Binance
    - download history from Bybit (convert to Finam TXT)

    Reikalavimai iš host class (ParamsTab):
    - self.entry_history : tk.Entry
    - self.frame        : tk.Frame (nebūtina, bet dažnai būna)
    """

    # ---------------- callbacks ----------------

    def on_browse_file(self):
        path = filedialog.askopenfilename(
            title="Pasirinkite istorijos failą",
            filetypes=[("TXT files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.entry_history.delete(0, tk.END)
            self.entry_history.insert(0, path)

    def on_merge_files(self):
        input_paths = filedialog.askopenfilenames(
            title="Pasirinkite Finam TXT failus sujungimui",
            filetypes=[("TXT files", "*.txt"), ("All files", "*.*")],
        )
        if not input_paths:
            return

        out_path = filedialog.asksaveasfilename(
            title="Kur išsaugoti sujungtą failą",
            defaultextension=".txt",
            filetypes=[("TXT files", "*.txt"), ("All files", "*.*")],
        )
        if not out_path:
            return

        try:
            info = merge_finam_files(list(input_paths), out_path)
        except Exception as e:
            messagebox.showerror("Klaida", f"Nepavyko sujungti failų:\n{e}")
            return

        self.entry_history.delete(0, tk.END)
        self.entry_history.insert(0, out_path)

        messagebox.showinfo(
            "Sukurta",
            f"Sujungta {info.get('files','?')} failų. Eilučių: {info.get('rows','?')}\nFailas: {info.get('output', out_path)}",
        )

    def on_download_btc(self):
        symbol = "BTCUSDT"
        year = simpledialog.askinteger("BTC download", "Metai (YYYY):", initialvalue=2023, minvalue=2017, maxvalue=2100)
        if not year:
            return
        interval = simpledialog.askstring("BTC download", "Intervalas (pvz. 1h, 30m, 4h, 1d):", initialvalue="1h")
        if not interval:
            return

        out_path = filedialog.asksaveasfilename(
            title="Kur išsaugoti BTC istoriją (TXT)",
            defaultextension=".txt",
            filetypes=[("TXT files", "*.txt"), ("All files", "*.*")],
            initialfile=f"BTCUSDT_{interval}_{year}.txt",
        )
        if not out_path:
            return

        try:
            download_binance_klines(
                symbol=symbol,
                interval=interval,
                start_date=f"{year}-01-01",
                end_date=f"{year}-12-31",
                output_path=out_path,
            )
        except Exception as e:
            messagebox.showerror("Klaida", f"Nepavyko atsisiųsti BTC duomenų:\n{e}")
            return

        self.entry_history.delete(0, tk.END)
        self.entry_history.insert(0, out_path)
        messagebox.showinfo("Baigta", f"Atsisiųsta BTC istorija.\nFailas: {out_path}")

    def on_download_bybit(self):
        symbol = simpledialog.askstring("Bybit download", "Symbolis (pvz. BTCUSDT):", initialvalue="BTCUSDT")
        if not symbol:
            return
        interval = simpledialog.askstring("Bybit download", "Intervalas (pvz. 1m,5m,15m,30m,1h,4h,1d):", initialvalue="1h")
        if not interval:
            return
        start_date = simpledialog.askstring("Bybit download", "Data nuo (YYYY-MM-DD):", initialvalue="2023-01-01")
        if not start_date:
            return
        end_date = simpledialog.askstring("Bybit download", "Data iki (YYYY-MM-DD):", initialvalue="2023-12-31")
        if not end_date:
            return

        out_path = filedialog.asksaveasfilename(
            title="Kur išsaugoti Bybit istoriją (Finam TXT)",
            defaultextension=".txt",
            filetypes=[("TXT files", "*.txt"), ("All files", "*.*")],
            initialfile=f"{symbol}_{interval}_{start_date}_{end_date}_bybit.txt",
        )
        if not out_path:
            return

        try:
            download_bybit_to_finam_txt(
                symbol=symbol,
                interval_ui=interval,
                start_date=start_date,
                end_date=end_date,
                output_path=out_path,
            )
        except Exception as e:
            messagebox.showerror("Klaida", f"Nepavyko atsisiųsti Bybit duomenų:\n{e}")
            return

        self.entry_history.delete(0, tk.END)
        self.entry_history.insert(0, out_path)
        messagebox.showinfo("Baigta", f"Atsisiųsta Bybit istorija.\nFailas: {out_path}")
