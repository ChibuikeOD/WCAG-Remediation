"""Configure privacy and bundled tools before importing the remediation engine."""
from __future__ import annotations

import os
from pathlib import Path
import sys

_guard_installed = False


def _deny_network(event: str, args: tuple) -> None:
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg"}:
        raise PermissionError("PDFAccess Desktop blocks network access during local processing")


def configure_runtime() -> Path:
    global _guard_installed
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    os.environ.update({
        "LOCAL_ONLY": "true",
        "DEPLOYMENT_MODE": "testing",
        "DISABLE_AUTH": "true",
        "DISABLE_LAYOUTLM": "true",
        "PDF_UNICODE_LLM_ENABLED": "false",
        "JEV_STRUCTURE_REFINEMENT_ENABLED": "false",
        "JEV_GLYPH_CONSENSUS_ENABLED": "false",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "DISABLE_OPENDATALOADER": "false",
        "DISABLE_OCR": "false",
        "_JAVA_OPTIONS": "-Xmx512m -Djava.net.useSystemProxies=false",
        "OPENDATALOADER_ROOT": str(resources / "desktop-no-vendor-runtime"),
    })
    for name in list(os.environ):
        if name.endswith("_API_KEY") or name.startswith(("SUPABASE_", "STRIPE_", "VERCEL_", "OIDC_")):
            os.environ.pop(name, None)
    for name in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "DATABASE_POOLER_HOST"):
        os.environ.pop(name, None)
    state = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PDFAccess"
    state.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "UPLOAD_DIR": str(state / "scratch"),
        "OUTPUT_DIR": str(state / "scratch"),
        "ARTIFACT_STORAGE_ROOT": str(state / "scratch"),
        "DATABASE_URL": "sqlite:///:memory:",
        "RULES_DIR": str(resources / "rules"),
    })
    java = resources / "runtime" / "java" / "bin"
    native = resources / "pdfua_remediator_cpp" / "build" / "Release"
    if getattr(sys, "frozen", False):
        for required in (java / "java.exe", native / "pdfua-remediator-cli.exe",
                         native / "qpdf.exe", resources / "runtime" / "tessdata" / "eng.traineddata"):
            if not required.is_file():
                raise RuntimeError(f"The desktop download is incomplete: missing {required.name}. "
                                   "Extract the entire ZIP before opening the app.")
    os.environ["PATH"] = os.pathsep.join((str(java), str(native), os.environ.get("PATH", "")))
    tessdata = resources / "runtime" / "tessdata"
    if tessdata.is_dir():
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
    if not _guard_installed:
        sys.addaudithook(_deny_network)
        _guard_installed = True
    return resources
