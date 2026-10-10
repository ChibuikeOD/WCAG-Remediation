"""Produce a portable Windows download, verify it, and write release checksums."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def download(entry: dict, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]:
        with urllib.request.urlopen(entry["url"], timeout=120) as response, target.open("wb") as out:
            shutil.copyfileobj(response, out)
    if hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]:
        raise RuntimeError(f"Checksum mismatch: {target.name}")
    return target


def extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("Archive entry escapes its destination")
        zipped.extractall(destination)


def validate_bundle(archive: Path) -> None:
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        for name in names:
            path = Path(name)
            if path.suffix.lower() in {".pdf", ".db", ".sqlite", ".sqlite3"} or path.name.startswith(".env"):
                raise RuntimeError(f"Unexpected private/generated file in desktop download: {name}")
        if "PDFAccess/PDFAccess.exe" not in names:
            raise RuntimeError("Desktop download is missing its executable")


def prepare_runtime() -> None:
    cache = ROOT / ".cache" / "desktop"
    stage = cache / "bundle"
    lock = json.loads((ROOT / "desktop" / "runtime-lock.json").read_text())
    java_zip = download(lock["java"], cache / "java.zip")
    qpdf_zip = download(lock["qpdf"], cache / "qpdf.zip")
    ocr = download(lock["ocr"], cache / "eng.traineddata")
    extract(java_zip, cache / "java")
    java_home = next((cache / "java").glob("*/bin/java.exe")).parent.parent
    shutil.copytree(java_home, stage / "runtime" / "java", dirs_exist_ok=True)
    (stage / "runtime" / "tessdata").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ocr, stage / "runtime" / "tessdata" / ocr.name)
    native_source = cache / "native-source"
    native_source.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "pdfua_remediator_cpp" / "CMakeLists.txt", native_source)
    shutil.copytree(ROOT / "pdfua_remediator_cpp" / "src", native_source / "src", dirs_exist_ok=True)
    extract(qpdf_zip, native_source / "deps")
    native_build = cache / "native-build"
    subprocess.run(["cmake", "-S", str(native_source), "-B", str(native_build),
                    "-A", "x64"], check=True)
    subprocess.run(["cmake", "--build", str(native_build), "--config", "Release"], check=True)
    native = stage / "pdfua_remediator_cpp" / "build" / "Release"
    native.mkdir(parents=True, exist_ok=True)
    shutil.copy2(native_build / "Release" / "pdfua-remediator-cli.exe", native)
    qpdf = native_source / "deps" / "qpdf-12.3.2-msvc64"
    for path in (qpdf / "bin").iterdir():
        if path.suffix.lower() == ".dll" or path.name == "qpdf.exe":
            shutil.copy2(path, native / path.name)
    notices = stage / "notices"
    notices.mkdir(parents=True, exist_ok=True)
    shutil.copytree(qpdf / "share" / "doc" / "qpdf", notices / "qpdf", dirs_exist_ok=True)
    # Include upstream license text for OCR data and the Java runtime.
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/"
        "87416418657359cb625c412a48b6e1d6d41c29bd/LICENSE", notices / "tessdata-LICENSE")
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        for index, file in enumerate(distribution.files or []):
            if re.search(r"(?:license|copying|notice)", Path(str(file)).name, re.I):
                source = Path(distribution.locate_file(file))
                if source.is_file() and source.suffix.lower() not in {".py", ".pyc"}:
                    dest = notices / name / f"{index}-{source.name}"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="1.0.0")
    options = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows downloads must be built on Windows")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", options.version):
        parser.error("Use a semantic release version")
    os.chdir(ROOT)
    prepare_runtime()
    # APP_VERSION is baked into a generated runtime hook, not read from a cloud env file.
    hook = ROOT / ".cache" / "desktop" / "version_hook.py"
    hook.write_text(f"import os\nos.environ['APP_VERSION'] = {options.version!r}\n", encoding="utf-8")
    # Spec runtime hooks are resolved here through an explicit build-only env variable.
    os.environ["PDFACCESS_VERSION_HOOK"] = str(hook)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "desktop/PDFAccess.spec"], check=True)
    app = ROOT / "dist" / "PDFAccess"
    smoke = ROOT / ".artifacts" / "desktop-packaged-smoke"
    result_path = smoke / "result.json"
    result_path.unlink(missing_ok=True)
    completed = subprocess.run([str(app / "PDFAccess.exe"), "--self-test", str(smoke),
                                "--result-json", str(result_path)], timeout=240)
    result = json.loads(result_path.read_text()) if result_path.is_file() else {}
    if completed.returncode or result.get("ok") is not True:
        raise RuntimeError(f"Packaged desktop smoke test failed: {result}")
    # Keep run metadata outside the downloadable app; no test documents are shipped.
    shutil.copy2(ROOT / "desktop" / "README.md", app / "README.md")
    filename = f"PDFAccess-{options.version}-windows-x64"
    archive = Path(shutil.make_archive(str(ROOT / "dist" / filename), "zip", ROOT / "dist", "PDFAccess"))
    validate_bundle(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (ROOT / "dist" / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    manifest = {"version": options.version, "platform": "windows-x64", "filename": archive.name,
                "sha256": digest, "bytes": archive.stat().st_size, "local_processing": True,
                "update_policy": "manual-download", "smoke_test": result}
    manifest["source_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    manifest["working_tree_dirty"] = bool(subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], text=True).strip())
    (ROOT / "dist" / "desktop-release.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Download ready: {archive}")


if __name__ == "__main__":
    main()
