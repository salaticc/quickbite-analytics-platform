"""Stream CSV output and validate a checksummed manifest before loading."""

import csv
from dataclasses import asdict
from hashlib import file_digest as hash_file, sha256
import json
from pathlib import Path
from contextlib import ExitStack

from .contracts import TABLES, BUSINESS_ZONE
from .config import Config

FORMAT = 1


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hash_file(stream, "sha256").hexdigest()


class ArtifactWriter:
    def __init__(self, path: Path, stack: ExitStack):
        self.counts = dict.fromkeys((table.name for table in TABLES), 0)
        self.writers = {}
        for table in TABLES:
            file = stack.enter_context((path / f"{table.name}.csv").open("w", newline="", encoding="utf-8"))
            writer = csv.writer(file, lineterminator="\n")
            writer.writerow(table.columns)
            self.writers[table.name] = writer

    def row(self, table: str, *fields) -> None:
        self.writers[table].writerow(fields)
        self.counts[table] += 1


def write_manifest(path: Path, config: Config, counts: dict[str, int]) -> dict:
    entries = {
        name: {"rows": count, "sha256": file_digest(path / f"{name}.csv")}
        for name, count in counts.items()
    }
    manifest = {
        "format": FORMAT,
        "business_zone": BUSINESS_ZONE,
        "currency": "RUB",
        "generation_parameters": asdict(config),
        "tables": entries,
    }
    content = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (path / "manifest.json").write_text(content, encoding="utf-8", newline="\n")
    return manifest


def validate_manifest(path: Path) -> tuple[dict, str]:
    content = (path / "manifest.json").read_bytes()
    manifest = json.loads(content)
    if manifest["format"] != FORMAT or set(manifest["tables"]) != {t.name for t in TABLES}:
        raise ValueError("Dataset manifest version or table list is unsupported")
    for table in TABLES:
        file = path / f"{table.name}.csv"
        entry = manifest["tables"][table.name]
        if file_digest(file) != entry["sha256"]:
            raise ValueError(f"{table.name}: CSV checksum does not match manifest")
        with file.open(newline="", encoding="utf-8") as stream:
            reader = csv.reader(stream)
            if tuple(next(reader, ())) != table.columns:
                raise ValueError(f"{table.name}: unexpected CSV header")
            if sum(1 for _ in reader) != entry["rows"]:
                raise ValueError(f"{table.name}: CSV row count does not match manifest")
    return manifest, sha256(content).hexdigest()
