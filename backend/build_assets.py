"""Bundle shared WCAG rule definitions into the Vercel backend service."""

from pathlib import Path
from shutil import copytree


def bundle_rules(destination: Path) -> None:
    source = Path(__file__).resolve().parent.parent / "rules"
    if not source.is_dir():
        raise FileNotFoundError(f"WCAG rules directory is missing: {source}")
    copytree(source, destination, dirs_exist_ok=True)


if __name__ == "__main__":
    bundle_rules(Path(__file__).resolve().parent / "rules")
