"""
app.py
================================================================================
Tkinter GUI for the MotionSolve PLT -> MF4 (AVL Drive) converter.

Same structure as the csv-to-mf4 app:
  - widgets are built once, callbacks wired to buttons,
  - conversions run on a worker thread so the window never freezes,
  - the worker reports through a Queue that the GUI drains every 100 ms.

Drag and drop works two ways:
  - drop .plt files onto the window itself (needs the tkinterdnd2 package;
    the app falls back to buttons-only if it isn't installed), or
  - drop them onto the built .exe icon (they arrive as sys.argv).
================================================================================
"""

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

from avl_extract import DEFAULT_PACK_VOLTAGE
from converter import convert

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False


def set_window_icon(root, icon_name):
    """Give the window (and its taskbar button) the app's own icon.

    PyInstaller unpacks files bundled with --add-data into a temp folder
    exposed as sys._MEIPASS; running from source, the .ico sits in assets/
    next to this file. The icon is cosmetic, so never let it stop the app.
    """
    base = getattr(sys, "_MEIPASS", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "assets"))
    try:
        root.iconbitmap(os.path.join(base, icon_name))
    except Exception:
        pass


class PltConverterApp:
    def __init__(self, root):
        self.root = root
        root.title("MotionSolve PLT → MF4 Converter  (AVL Drive)")
        root.geometry("760x520")
        root.minsize(600, 400)
        set_window_icon(root, "plttomf4.ico")

        self.files = []                 # .plt paths queued for conversion
        self.log_queue = queue.Queue()  # worker thread -> GUI messages
        self.working = False

        # --- top row: file selection buttons --------------------------------
        top = tk.Frame(root)
        top.pack(fill="x", padx=10, pady=(10, 5))

        tk.Button(top, text="Add PLT file(s)…",
                  command=self.pick_files).pack(side="left")
        tk.Button(top, text="Add folder…",
                  command=self.pick_folder).pack(side="left", padx=(6, 0))
        tk.Button(top, text="Clear list",
                  command=self.clear_files).pack(side="left", padx=(6, 0))

        self.csv_var = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="Also write CSV",
                       variable=self.csv_var).pack(side="right")

        # pack voltage feeds the EM current estimate (I = Power Demand / V)
        self.voltage_var = tk.StringVar(value="{:g}".format(DEFAULT_PACK_VOLTAGE))
        tk.Entry(top, textvariable=self.voltage_var,
                 width=6, justify="right").pack(side="right", padx=(2, 12))
        tk.Label(top, text="Pack voltage [V]:").pack(side="right")

        # --- middle: list of queued files ------------------------------------
        drop_hint = " — drop .plt files here" if DND_AVAILABLE else ""
        mid = tk.LabelFrame(
            root, text="Files to convert (.mf4 is written next to each PLT)" + drop_hint)
        mid.pack(fill="both", expand=False, padx=10, pady=5)

        self.file_list = tk.Listbox(mid, height=6)
        self.file_list.pack(fill="both", expand=True, padx=5, pady=5)

        # --- convert button ---------------------------------------------------
        self.convert_btn = tk.Button(root, text="Convert", height=2,
                                     command=self.start_conversion)
        self.convert_btn.pack(fill="x", padx=10, pady=5)

        # --- bottom: log window ----------------------------------------------
        bottom = tk.LabelFrame(root, text="Log")
        bottom.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.log_box = scrolledtext.ScrolledText(bottom, state="disabled",
                                                 font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)

        # in-window drag and drop (whole window is a drop target)
        if DND_AVAILABLE:
            root.drop_target_register(DND_FILES)
            root.dnd_bind("<<Drop>>", self.on_drop)

        # files dropped onto the .exe icon arrive as command-line arguments
        for arg in sys.argv[1:]:
            self.add_path(arg)

        self.root.after(100, self.drain_log_queue)

    # --- file selection callbacks --------------------------------------------

    def add_path(self, path):
        """Add one .plt file, or every .plt inside a folder."""
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if name.lower().endswith(".plt"):
                    self.add_path(os.path.join(path, name))
        elif path.lower().endswith(".abf"):
            messagebox.showinfo(
                "ABF not supported",
                "{}\n\n.abf is a binary format - drop the run's .plt "
                "instead (it holds the same data).".format(os.path.basename(path)))
        elif path.lower().endswith(".plt") and path not in self.files:
            self.files.append(path)
            self.file_list.insert("end", path)

    def on_drop(self, event):
        for path in self.root.tk.splitlist(event.data):
            self.add_path(path)

    def pick_files(self):
        for path in filedialog.askopenfilenames(
                title="Select MotionSolve PLT file(s)",
                filetypes=[("MotionSolve plot files", "*.plt"),
                           ("All files", "*.*")]):
            self.add_path(path)

    def pick_folder(self):
        folder = filedialog.askdirectory(title="Select a folder of PLT files")
        if folder:
            before = len(self.files)
            self.add_path(folder)
            if len(self.files) == before:
                messagebox.showinfo("No PLTs", "No .plt files found in that folder.")

    def clear_files(self):
        self.files = []
        self.file_list.delete(0, "end")

    # --- conversion (worker thread) -------------------------------------------

    def start_conversion(self):
        if self.working:
            return
        if not self.files:
            messagebox.showinfo("Nothing to convert",
                                "Add at least one .plt file first.")
            return

        try:
            voltage = float(self.voltage_var.get())
            if voltage <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Invalid pack voltage",
                "'{}' is not a valid pack voltage. Enter a positive number "
                "in volts (it feeds the EM current estimate)."
                .format(self.voltage_var.get()))
            return

        self.working = True
        self.convert_btn.config(state="disabled", text="Converting…")
        threading.Thread(target=self.worker,
                         args=(list(self.files), self.csv_var.get(), voltage),
                         daemon=True).start()

    def worker(self, paths, write_csv, voltage):
        """Runs on the background thread. GUI access only via the queue."""
        log = self.log_queue.put
        ok = failed = 0
        for plt_path in paths:
            log("Converting: " + os.path.basename(plt_path))
            try:
                convert(plt_path, write_csv=write_csv, log=log,
                        pack_voltage=voltage)
                ok += 1
            except Exception as exc:
                log("  ERROR: {}".format(exc))
                failed += 1
            log("")
        log("Done: {} converted, {} failed.".format(ok, failed))
        log(("__DONE_OK__", "__DONE_FAIL__")[failed > 0])

    # --- GUI-thread queue polling ----------------------------------------------

    def drain_log_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line in ("__DONE_OK__", "__DONE_FAIL__"):
                    self.working = False
                    self.convert_btn.config(state="normal", text="Convert")
                    continue
                self.log_box.config(state="normal")
                self.log_box.insert("end", line + "\n")
                self.log_box.see("end")
                self.log_box.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self.drain_log_queue)


def main():
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    PltConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
