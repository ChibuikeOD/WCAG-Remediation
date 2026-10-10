"""Native Windows UI and headless packaged-app smoke test."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import sys
import threading

from desktop.runtime import configure_runtime


def self_test(destination: Path) -> dict:
    """Exercise bundled Java, native tagging, OCR, analysis, and report generation."""
    from desktop.service import remediate_local
    import fitz
    import pikepdf
    import socket
    import tkinter as tk

    window = tk.Tk()
    window.withdraw()
    window.update()
    window.destroy()
    try:
        socket.getaddrinfo("example.com", 443)
    except PermissionError:
        pass
    else:
        raise RuntimeError("The desktop privacy guard did not block network access")

    destination.mkdir(parents=True, exist_ok=True)
    sample = destination / "sample.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "PDFAccess local remediation smoke test")
        page.insert_text((72, 110), "This document stays on the device.")
        document.save(sample)
    result = remediate_local(sample, destination)
    tagging = next(r for r in result["results"] if r["issue_id"] == "pdf-auto-tag")
    if not tagging["success"]:
        raise RuntimeError(f"Bundled tagging failed: {tagging['message']}")
    with pikepdf.open(result["remediated_pdf"]) as pdf:
        if "/StructTreeRoot" not in pdf.Root or not pdf.Root.get("/Lang"):
            raise RuntimeError("Smoke test output is missing structure or language")
    with fitz.open(sample) as document:
        pix = document[0].get_pixmap()
        ocr_pdf = pix.pdfocr_tobytes(language="eng", tessdata=os.environ.get("TESSDATA_PREFIX"))
        with fitz.open(stream=ocr_pdf, filetype="pdf") as searchable:
            if "PDFAccess" not in searchable[0].get_text():
                raise RuntimeError("Bundled OCR did not produce searchable text")
    return {"ok": True, "tagging": True, "ocr": True, "ui": True,
            "network_blocked": True, "cloud_ai_used": False}


def show_app() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from desktop.service import remediate_local
    from backend.config import settings

    root = tk.Tk()
    root.title(f"PDFAccess Desktop {settings.APP_VERSION}")
    root.geometry("800x580")
    root.minsize(640, 470)
    panel = ttk.Frame(root, padding=24)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="PDFAccess Desktop", font=("Segoe UI", 23, "bold")).pack(anchor="w")
    ttk.Label(panel, text="Private PDF remediation • Windows • on-device processing",
              font=("Segoe UI", 11)).pack(anchor="w", pady=(8, 16))
    ttk.Label(panel, text="Your PDF and its contents stay on this device. No account or internet is required.\n"
              "Cloud AI is disabled. Review figure descriptions and remaining findings yourself.",
              wraplength=720).pack(anchor="w", pady=(0, 18))
    source = tk.StringVar()
    output = tk.StringVar(value=str(Path.home() / "Documents" / "PDFAccess Outputs"))
    status = tk.StringVar(value="Choose a PDF and an output folder to begin.")
    events: queue.Queue = queue.Queue()
    state = {"busy": False, "result": None}
    controls = []
    for label, variable, picker in (
        ("PDF document", source, lambda: filedialog.askopenfilename(filetypes=[("PDF documents", "*.pdf")])),
        ("Output folder", output, lambda: filedialog.askdirectory()),
    ):
        ttk.Label(panel, text=label).pack(anchor="w")
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=(4, 12))
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side="left", fill="x", expand=True)
        def choose(var=variable, select=picker):
            value = select()
            if value:
                var.set(value)
        button = ttk.Button(row, text="Browse…", command=choose)
        button.pack(side="left", padx=(8, 0))
        controls.extend((entry, button))

    def start():
        if not source.get() or not output.get():
            messagebox.showerror("Choose paths", "Choose a PDF and an output folder.")
            return
        state.update(busy=True, result=None)
        open_button.configure(state="disabled")
        for control in controls:
            control.configure(state="disabled")
        progress.start()
        selected_source, selected_output = Path(source.get()), Path(output.get())
        def worker():
            try:
                result = remediate_local(selected_source, selected_output,
                                         lambda text: events.put(("progress", text)))
                events.put(("complete", result))
            except Exception as exc:
                events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    start_button = ttk.Button(panel, text="Remediate on this device", command=start)
    start_button.pack(anchor="w", pady=(4, 12))
    controls.append(start_button)
    progress = ttk.Progressbar(panel, mode="indeterminate")
    progress.pack(fill="x", pady=(0, 12))
    ttk.Label(panel, textvariable=status, wraplength=720).pack(anchor="w")
    details = tk.Text(panel, height=8, wrap="word", font=("Segoe UI", 10), state="disabled")
    details.pack(fill="both", expand=True, pady=12)
    open_button = ttk.Button(panel, text="Open output folder", state="disabled",
                             command=lambda: os.startfile(state["result"]["output_directory"]))
    open_button.pack(anchor="w")

    def poll():
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == "progress":
                    status.set(value)
                    continue
                state["busy"] = False
                progress.stop()
                for control in controls:
                    control.configure(state="normal")
                if kind == "error":
                    status.set("Processing failed. Your original PDF is unchanged.")
                    messagebox.showerror("Remediation failed", value)
                else:
                    state["result"] = value
                    open_button.configure(state="normal")
                    failed = sum(not r["success"] for r in value["results"])
                    status.set(f"Saved locally. {failed} steps need attention; "
                               f"{value['after']['total_issues']} findings remain for review.")
                    details.configure(state="normal")
                    details.delete("1.0", "end")
                    details.insert("end", value["review_note"] + "\n\n")
                    for result in value["results"]:
                        details.insert("end", f"{'OK' if result['success'] else 'REVIEW'}: {result['message']}\n")
                    details.configure(state="disabled")
        except queue.Empty:
            pass
        root.after(150, poll)

    def close():
        if state["busy"]:
            messagebox.showinfo("Processing", "Wait for remediation to finish before closing the app.")
        else:
            root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(150, poll)
    root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description="PDFAccess on-device PDF remediation")
    parser.add_argument("--self-test", type=Path, metavar="OUTPUT_DIR")
    parser.add_argument("--remediate", type=Path, metavar="PDF")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--result-json", type=Path)
    options = parser.parse_args()
    result = None
    try:
        configure_runtime()
        if options.self_test:
            result = self_test(options.self_test)
        elif options.remediate:
            if not options.output_dir:
                parser.error("--remediate requires --output-dir")
            from desktop.service import remediate_local
            result = remediate_local(options.remediate, options.output_dir)
        else:
            show_app()
        code = 0
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        code = 1
        if not options.self_test and not options.remediate:
            from tkinter import messagebox
            messagebox.showerror("PDFAccess could not start", str(exc))
    if options.result_json and result is not None:
        options.result_json.parent.mkdir(parents=True, exist_ok=True)
        options.result_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if result is not None and sys.stdout is not None:
        print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
