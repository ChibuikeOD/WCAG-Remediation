from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_frontend_does_not_offer_structure_rebuild_opt_out():
    panel_source = (
        REPO_ROOT / "frontend/src/components/RemediationPanel.tsx"
    ).read_text(encoding="utf-8")
    api_source = (REPO_ROOT / "frontend/src/api.ts").read_text(encoding="utf-8")
    types_source = (REPO_ROOT / "frontend/src/types.ts").read_text(encoding="utf-8")

    assert "Rebuild structure with OpenDataLoader" not in panel_source
    assert "overwriteTags" not in panel_source
    assert "overwrite_tags" not in api_source
    assert "overwrite_tags" not in types_source
