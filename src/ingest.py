"""Idempotent downloader for StatCan bulk CSV tables.

For each table it asks StatCan whether the file changed since the last recorded download
and only downloads when it did. Decisions:

- Conditional GET (If-Modified-Since / If-None-Match) instead of HEAD then GET. One round
  trip, and a server that ignores the condition still works because we also compare the
  returned Last-Modified against the manifest before writing anything.
- Downloads stream to a ".part" file and are renamed only when complete, so a dropped
  connection never leaves a truncated zip that a later run would mistake for valid data.
- The zip is unpacked by streaming the one data CSV out of it (the archive also holds a
  metadata CSV we do not need). Memory stays flat even for the 1.18 GB LFS file.
- A file is skipped only if it is unchanged remotely AND present locally. A fresh clone has
  the committed manifest but no raw files, and must still download.

Usage:
    python -m src.ingest            download whatever changed
    python -m src.ingest --check    report changes only: exit 1 if anything changed, 0 if not,
                                    2 if StatCan could not be reached
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.config import MANIFEST_PATH, RAW_DIR, TABLES, table_url

CHUNK = 1024 * 1024
TIMEOUT = (15, 120)  # (connect, read) seconds; StatCan can be slow to start large files


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_manifest(manifest: dict, path: Path = MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def csv_path(pid: str, raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / f"{pid}.csv"


def _conditional_headers(entry: dict | None) -> dict:
    headers = {}
    if entry:
        if entry.get("last_modified"):
            headers["If-Modified-Since"] = entry["last_modified"]
        if entry.get("etag"):
            headers["If-None-Match"] = entry["etag"]
    return headers


def has_changed(pid: str, entry: dict | None, url: str, session: requests.Session) -> bool:
    """HEAD check used by --check mode, where we must not download anything."""
    resp = session.head(url, timeout=TIMEOUT, allow_redirects=True)
    resp.raise_for_status()
    if not entry:
        return True
    return resp.headers.get("Last-Modified") != entry.get("last_modified")


def _extract_data_csv(zip_path: Path, pid: str, out_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        # The archive holds "<pid>.csv" and "<pid>_MetaData.csv"; we want the first.
        member = f"{pid}.csv"
        if member not in zf.namelist():
            raise ValueError(f"{zip_path.name} has no {member}; found {zf.namelist()}")
        tmp = out_path.with_suffix(".csv.part")
        with zf.open(member) as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst, CHUNK)
        tmp.replace(out_path)


def fetch_table(
    pid: str,
    manifest: dict,
    session: requests.Session,
    url: str | None = None,
    raw_dir: Path = RAW_DIR,
) -> str:
    """Download one table if needed. Returns "skipped", "downloaded" or "unchanged-refetched"."""
    url = url or table_url(pid)
    entry = manifest.get(pid)
    out_csv = csv_path(pid, raw_dir)
    local_ok = out_csv.exists()

    # Only send conditions when we actually hold the file; otherwise a 304 would leave us
    # with nothing on disk.
    headers = _conditional_headers(entry) if local_ok else {}
    resp = session.get(url, headers=headers, stream=True, timeout=TIMEOUT)
    if resp.status_code == 304:
        resp.close()
        return "skipped"
    resp.raise_for_status()

    last_modified = resp.headers.get("Last-Modified")
    if local_ok and entry and last_modified and last_modified == entry.get("last_modified"):
        # Server ignored our condition but the file is the same version we have.
        resp.close()
        return "skipped"

    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / f"{pid}-eng.zip"
    part = zip_path.with_suffix(".zip.part")
    sha = hashlib.sha256()
    size = 0
    with open(part, "wb") as fh:
        for chunk in resp.iter_content(CHUNK):
            fh.write(chunk)
            sha.update(chunk)
            size += len(chunk)
    expected = resp.headers.get("Content-Length")
    if expected is not None and int(expected) != size:
        part.unlink(missing_ok=True)
        raise IOError(f"{pid}: got {size} bytes, server promised {expected}")
    part.replace(zip_path)

    _extract_data_csv(zip_path, pid, out_csv)
    # The zip is only a transport container; keeping it would double disk use for LFS.
    zip_path.unlink()

    manifest[pid] = {
        "url": url,
        "last_modified": last_modified,
        "etag": resp.headers.get("ETag"),
        "zip_bytes": size,
        "zip_sha256": sha.hexdigest(),
        "csv_bytes": out_csv.stat().st_size,
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return "downloaded"


def run(check_only: bool = False, tables: dict = TABLES) -> int:
    manifest = load_manifest()
    session = requests.Session()
    session.headers["User-Agent"] = "project5-canada-economy-platform (portfolio project)"

    if check_only:
        try:
            changed = [pid for pid in tables if has_changed(pid, manifest.get(pid), table_url(pid), session)]
        except requests.RequestException as err:
            # Exit 2, not 1: the scheduler reads 1 as "data changed", and a network error is not that.
            print(f"check failed: {err}", file=sys.stderr)
            return 2
        for pid in tables:
            print(f"{pid}: {'CHANGED' if pid in changed else 'unchanged'}")
        return 1 if changed else 0

    for pid, label in tables.items():
        status = fetch_table(pid, manifest, session)
        print(f"{pid} [{label}]: {status}")
        # Save after every table so a failure on table 4 does not forget tables 1 to 3.
        save_manifest(manifest)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="only report whether StatCan published new data")
    args = parser.parse_args(argv)
    return run(check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
