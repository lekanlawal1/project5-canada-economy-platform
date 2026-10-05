"""Downloader tests against a local HTTP server, so they run offline and in CI.

Python's built in SimpleHTTPRequestHandler sends Last-Modified and answers 304 to
If-Modified-Since, which is the behaviour we rely on from StatCan.
"""

import functools
import http.server
import os
import threading
import zipfile

import pytest
import requests

from src import ingest

PID = "99990001"


@pytest.fixture
def server(tmp_path):
    serve_dir = tmp_path / "serve"
    serve_dir.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(serve_dir))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield serve_dir, f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def write_zip(serve_dir, body: str, mtime: int):
    path = serve_dir / f"{PID}-eng.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{PID}.csv", body)
        zf.writestr(f"{PID}_MetaData.csv", "ignored")
    os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def session():
    # Bypass the sandbox proxy for localhost.
    s = requests.Session()
    s.trust_env = False
    return s


def test_first_run_downloads_and_extracts(server, session, tmp_path):
    serve_dir, base = server
    write_zip(serve_dir, "REF_DATE,VALUE\n2026-01,1.0\n", 1_700_000_000)
    raw = tmp_path / "raw"
    manifest = {}

    status = ingest.fetch_table(PID, manifest, session, url=f"{base}/{PID}-eng.zip", raw_dir=raw)

    assert status == "downloaded"
    assert (raw / f"{PID}.csv").read_text() == "REF_DATE,VALUE\n2026-01,1.0\n"
    assert not (raw / f"{PID}-eng.zip").exists(), "zip should be deleted after extraction"
    assert manifest[PID]["last_modified"]


def test_second_run_skips_when_unchanged(server, session, tmp_path):
    serve_dir, base = server
    write_zip(serve_dir, "REF_DATE,VALUE\n2026-01,1.0\n", 1_700_000_000)
    raw, manifest, url = tmp_path / "raw", {}, f"{base}/{PID}-eng.zip"
    ingest.fetch_table(PID, manifest, session, url=url, raw_dir=raw)

    assert ingest.fetch_table(PID, manifest, session, url=url, raw_dir=raw) == "skipped"


def test_redownloads_when_remote_is_newer(server, session, tmp_path):
    serve_dir, base = server
    write_zip(serve_dir, "REF_DATE,VALUE\n2026-01,1.0\n", 1_700_000_000)
    raw, manifest, url = tmp_path / "raw", {}, f"{base}/{PID}-eng.zip"
    ingest.fetch_table(PID, manifest, session, url=url, raw_dir=raw)

    write_zip(serve_dir, "REF_DATE,VALUE\n2026-01,1.0\n2026-02,2.0\n", 1_800_000_000)

    assert ingest.fetch_table(PID, manifest, session, url=url, raw_dir=raw) == "downloaded"
    assert "2026-02" in (raw / f"{PID}.csv").read_text()


def test_fresh_clone_downloads_even_if_manifest_says_current(server, session, tmp_path):
    """The manifest is committed but raw files are not: a new checkout must still fetch."""
    serve_dir, base = server
    write_zip(serve_dir, "REF_DATE,VALUE\n2026-01,1.0\n", 1_700_000_000)
    raw, manifest, url = tmp_path / "raw", {}, f"{base}/{PID}-eng.zip"
    ingest.fetch_table(PID, manifest, session, url=url, raw_dir=raw)
    (raw / f"{PID}.csv").unlink()

    assert ingest.fetch_table(PID, manifest, session, url=url, raw_dir=raw) == "downloaded"
    assert (raw / f"{PID}.csv").exists()


def test_zip_without_expected_member_fails_loudly(server, session, tmp_path):
    serve_dir, base = server
    path = serve_dir / f"{PID}-eng.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("something_else.csv", "x")

    with pytest.raises(ValueError, match="has no"):
        ingest.fetch_table(PID, {}, session, url=f"{base}/{PID}-eng.zip", raw_dir=tmp_path / "raw")


def test_check_mode_exit_codes_drive_the_scheduler(server, tmp_path, monkeypatch):
    """0 = nothing new (scheduler stops), 1 = something changed (rebuild), 2 = StatCan unreachable."""
    serve_dir, base = server
    write_zip(serve_dir, "REF_DATE,VALUE\n2026-01,1.0\n", 1_700_000_000)
    s = requests.Session(); s.trust_env = False
    manifest = {}
    ingest.fetch_table(PID, manifest, s, url=f"{base}/{PID}-eng.zip", raw_dir=tmp_path / "raw")
    monkeypatch.setattr(ingest, "load_manifest", lambda: manifest)
    monkeypatch.setattr(ingest.requests, "Session", lambda: s)
    monkeypatch.setattr(ingest, "table_url", lambda pid: f"{base}/{pid}-eng.zip")
    tables = {PID: "test table"}

    assert ingest.run(check_only=True, tables=tables) == 0
    write_zip(serve_dir, "REF_DATE,VALUE\n2026-02,2.0\n", 1_800_000_000)
    assert ingest.run(check_only=True, tables=tables) == 1
    monkeypatch.setattr(ingest, "table_url", lambda pid: "http://127.0.0.1:9/unreachable.zip")
    assert ingest.run(check_only=True, tables=tables) == 2
