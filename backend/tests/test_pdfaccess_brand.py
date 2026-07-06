from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PRODUCT_NAMES = (
    "AccessPDF",
    "WCAG Accessibility Platform",
    "WCAG Accessibility Remediation Platform",
    "WCAG 2.2 Accessibility Remediation Platform",
    "PDF Accessibility Remediation Report",
)


def user_facing_files() -> list[Path]:
    return [
        ROOT / "frontend" / "index.html",
        *sorted((ROOT / "frontend" / "src").rglob("*.tsx")),
        ROOT / "backend" / "config.py",
        ROOT / "backend" / "main.py",
        ROOT / "backend" / "remediation_report.py",
        ROOT / "README.md",
    ]


def test_user_facing_product_name_is_pdfaccess() -> None:
    violations: list[str] = []

    for path in user_facing_files():
        content = path.read_text(encoding="utf-8").casefold()
        for product_name in FORBIDDEN_PRODUCT_NAMES:
            if product_name.casefold() in content:
                violations.append(f"{path.relative_to(ROOT)}: {product_name}")

    assert not violations, "Legacy product names found:\n" + "\n".join(violations)
