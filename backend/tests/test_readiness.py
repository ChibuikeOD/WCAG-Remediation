from unittest.mock import MagicMock

from backend import readiness


def test_readiness_checks_database_and_tools(monkeypatch):
    from backend.opendataloader_layout import OpenDataLoaderLayoutAnalyzer
    monkeypatch.setattr(readiness.settings, "DISABLE_OPENDATALOADER", True)
    monkeypatch.setattr(readiness.settings, "DISABLE_OCR", True)
    monkeypatch.setattr(readiness.shutil, "which", lambda _: "qpdf")
    monkeypatch.setattr(readiness, "engine", MagicMock())
    assert all(readiness.deployment_readiness().values())


def test_readiness_fails_closed_when_database_is_down(monkeypatch):
    unavailable = MagicMock()
    unavailable.connect.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(readiness, "engine", unavailable)
    assert readiness.deployment_readiness()["database"] is False
