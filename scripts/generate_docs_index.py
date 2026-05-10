from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
DOCS_INDEX = ROOT / "docs" / "index.md"
DOCS_CONTRIBUTING = ROOT / "docs" / "CONTRIBUTING.md"
URL = "https://github.com/sjmf/kvm-serial"


def generate_index() -> None:
    content = README.read_text(encoding="utf-8")

    # Strip docs/ prefix from all markdown link paths: (docs/X) -> (X)
    content = re.sub(r"\(docs/([^\)]+)\)", r"(\1)", content)
    # Also handle ./docs/ paths: (./docs/X) -> (X)
    content = re.sub(r"\(\./docs/([^\)]+)\)", r"(\1)", content)

    # External root-level docs need GitHub URLs
    content = content.replace("(LICENSE.md)", f"({URL}/blob/main/LICENSE.md)")
    content = content.replace("(CONTRIBUTING.md)", f"({URL}/blob/main/CONTRIBUTING.md)")

    # Asset URLs need to be absolute for docs site
    content = content.replace(
        'src="assets/icon.png"',
        'src="https://raw.githubusercontent.com/sjmf/kvm-serial/main/assets/icon.png"',
    )

    DOCS_INDEX.write_text(content, encoding="utf-8")


def generate_contributing() -> None:
    content = CONTRIBUTING.read_text(encoding="utf-8")

    # Relative GitHub issue links need absolute URLs for the docs site
    content = re.sub(r"\(\.\.\/\.\.\/issues", f"({URL}/issues", content)

    # README link becomes Home (the docs index page)
    content = content.replace("[README](README.md)", "[Home](index.md)")

    DOCS_CONTRIBUTING.write_text(content, encoding="utf-8")


def main() -> None:
    generate_index()
    generate_contributing()


if __name__ == "__main__":
    main()
