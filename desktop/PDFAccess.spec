"""Build on Windows; runtime preparation is handled by build_desktop.py."""
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
stage = root / ".cache" / "desktop" / "bundle"
odl_data, odl_binaries, odl_imports = collect_all("opendataloader_pdf")
datas = odl_data + copy_metadata("opendataloader-pdf") + [
    (str(root / "rules"), "rules"),
    (str(stage / "runtime"), "runtime"),
    (str(root / "desktop" / "README.md"), "."),
]
for notice in (stage / "notices").rglob("*"):
    if notice.is_file() and notice.suffix.lower() not in {".pdf", ".db", ".sqlite", ".sqlite3"}:
        datas.append((str(notice), str(Path("notices") / notice.relative_to(stage / "notices").parent)))
native = stage / "pdfua_remediator_cpp" / "build" / "Release"
binaries = odl_binaries + [(str(path), "pdfua_remediator_cpp/build/Release")
                          for path in native.iterdir() if path.suffix.lower() in {".dll", ".exe"}]
a = Analysis(
    [str(root / "desktop" / "launcher.py")], pathex=[str(root)], datas=datas, binaries=binaries,
    hiddenimports=odl_imports, hookspath=[], runtime_hooks=[os.environ["PDFACCESS_VERSION_HOOK"]],
    excludes=["torch", "transformers", "pytest", "backend.main", "backend.database",
              "backend.auth", "backend.payments", "playwright", "stripe"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PDFAccess", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PDFAccess")
