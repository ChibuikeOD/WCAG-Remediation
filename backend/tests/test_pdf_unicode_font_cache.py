from pathlib import Path

from backend import pdf_unicode_mapping as mapping


def test_font_evidence_cached_per_font_and_not_across_documents(monkeypatch):
    findings = [mapping.MissingUnicodeFinding((5, 0), "Font", cid, cid, ()) for cid in range(100)]
    findings.append(mapping.MissingUnicodeFinding((6, 0), "OtherFont", 1, 1, ()))
    monkeypatch.setattr(mapping, "inventory_missing_unicode", lambda path: findings)
    calls = []
    def collect(path, finding):
        calls.append((path, finding.font_objgen))
        return mapping.FontEvidence({}, {}, {})
    monkeypatch.setattr(mapping, "collect_font_evidence", collect)
    first = mapping.repair_missing_unicode(Path("first.pdf"))
    second = mapping.repair_missing_unicode(Path("second.pdf"))
    assert calls == [(Path("first.pdf"), (5, 0)), (Path("first.pdf"), (6, 0)),
                     (Path("second.pdf"), (5, 0)), (Path("second.pdf"), (6, 0))]
    assert first["details"]["unresolved"] == second["details"]["unresolved"] == 101
    assert first["details"]["llm_invoked"] is False
    assert [d["cid"] for d in first["details"]["decisions"]] == list(range(100)) + [1]


def test_conflicting_cached_evidence_remains_unresolved(monkeypatch):
    finding = mapping.MissingUnicodeFinding((5, 0), "Font", 1, 1, ())
    monkeypatch.setattr(mapping, "inventory_missing_unicode", lambda path: [finding])
    monkeypatch.setattr(mapping, "collect_font_evidence", lambda path, item:
                        mapping.FontEvidence({1: ("1",)}, {1: "two"}, {"two": "2"}))
    result = mapping.repair_missing_unicode(Path("ambiguous.pdf"))
    assert result["details"]["unresolved"] == 1
    assert result["new_value"] == "0 Unicode mapping(s) added"
