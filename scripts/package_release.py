"""Package only source files; credentials, databases and environments stay local."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from release_files import source_files

root = Path(__file__).resolve().parents[1]
output = root / "releases"
output.mkdir(exist_ok=True)
destination = output / "linklane-1.0.0-source.zip"
with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
    for path in source_files(root):
        archive.write(path, Path("linklane") / path.relative_to(root))
print(f"Created {destination.name}: {destination.stat().st_size:,} bytes")
