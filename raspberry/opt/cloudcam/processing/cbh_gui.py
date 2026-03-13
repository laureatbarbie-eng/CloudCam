# /opt/cloudcam/processing/cbh_gui.py
import tkinter as tk
from pathlib import Path
import csv, time, threading

CSV_PATH = Path("/var/lib/cloudcam/results/vnogo.csv")

def read_last():
    if not CSV_PATH.exists():
        return None
    with CSV_PATH.open("r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
        if len(rows) <= 1:
            return None
        last = rows[-1]
        return {"cycle_id": int(last[0]), "ts": last[1], "vnogo_m": float(last[2])}

def updater(label):
    while True:
        data = read_last()
        if data:
            txt = f"cycle {data['cycle_id']}\n{data['ts']}\nVNOGO ≈ {data['vnogo_m']:.1f} м"
        else:
            txt = "Нет данных VNOGO"
        label.after(0, label.config, {"text": txt})
        time.sleep(10)

def main():
    root = tk.Tk()
    root.title("VNOGO Monitor")
    label = tk.Label(root, text="Нет данных", font=("Arial", 20))
    label.pack(padx=20, pady=20)
    t = threading.Thread(target=updater, args=(label,), daemon=True)
    t.start()
    root.mainloop()

if __name__ == "__main__":
    main()
