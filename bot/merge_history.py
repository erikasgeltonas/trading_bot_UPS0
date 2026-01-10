# bot/merge_history.py

import csv
from pathlib import Path


FINAM_FIELDS = [
    "<TICKER>",
    "<PER>",
    "<DATE>",
    "<TIME>",
    "<OPEN>",
    "<HIGH>",
    "<LOW>",
    "<CLOSE>",
    "<VOL>",
]


def merge_finam_files(input_paths: list[str], output_path: str) -> dict:
    """
    Sujungia kelis Finam .txt (CSV) failus į vieną:
    - perskaito visus įrašus
    - išmeta dublikatus pagal (<DATE>, <TIME>)
    - išrūšiuoja pagal laiką
    - išsaugo naują failą su standartinėmis Finam antraštėmis

    Grąžina info dict: {'files': n_files, 'rows': n_rows}
    """
    if not input_paths:
        raise ValueError("Nenurodyti įvesties failai.")

    merged: dict[tuple[str, str], dict] = {}
    tickers: set[str] = set()
    pers: set[str] = set()

    for p in input_paths:
        path = Path(p)
        if not path.exists():
            raise FileNotFoundError(f"Failas nerastas: {path}")

        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                date = row.get("<DATE>")
                time = row.get("<TIME>")
                if not date or not time:
                    # bloga eilutė – praleidžiam
                    continue
                key = (date, time)
                merged[key] = row  # jei dublikuojasi – paskutinis laimi

                t = row.get("<TICKER>")
                per = row.get("<PER>")
                if t:
                    tickers.add(t)
                if per:
                    pers.add(per)

    if not merged:
        raise RuntimeError("Nerasta nei vienos validžios eilutės.")

    # Papildoma sauga – jei keli skirtingi ticker/per, perspėjam
    if len(tickers) > 1 or len(pers) > 1:
        # vis tiek leisim sujungti, bet naudotoją perspėja GUI
        pass

    # išrūšiuojam pagal datą ir laiką (abu jau fiksuoto formato stringai)
    keys_sorted = sorted(merged.keys())

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FINAM_FIELDS)
        writer.writeheader()
        for k in keys_sorted:
            row = merged[k]
            out_row = {field: row.get(field, "") for field in FINAM_FIELDS}
            writer.writerow(out_row)

    return {
        "files": len(input_paths),
        "rows": len(keys_sorted),
        "tickers": list(tickers),
        "pers": list(pers),
        "output": str(out_path),
    }
