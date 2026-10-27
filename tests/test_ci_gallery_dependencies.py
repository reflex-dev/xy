"""The shared gallery bundle must be verified before privileged installation."""

from __future__ import annotations

import hashlib
import io
import json

import pytest
from scripts import ci_gallery_dependencies as deps


@pytest.fixture
def bundle(tmp_path):
    data = b"pinned Ubuntu package"
    package = {
        "name": "ffmpeg",
        "version": "1:1.0-1",
        "architecture": "amd64",
        "filename": "ffmpeg_1.0-1_amd64.deb",
        "size": len(data),
        "sha512": hashlib.sha512(data).hexdigest(),
        "url": "https://archive.ubuntu.com/ubuntu/pool/universe/f/ffmpeg/test.deb",
    }
    lock = tmp_path / "lock.json"
    lock.write_text(
        json.dumps({"schema_version": 1, "platform": "ubuntu-24.04-amd64", "packages": [package]})
    )
    directory = tmp_path / "bundle"
    directory.mkdir()
    (directory / package["filename"]).write_bytes(data)
    return lock, directory, package


def test_valid_cache_does_not_contact_package_servers(bundle, monkeypatch):
    lock, directory, _ = bundle
    monkeypatch.setattr(deps, "urlopen", lambda *a, **kw: pytest.fail("cache hit used network"))
    deps.download(directory, deps.load_lock(lock))


def test_cold_download_is_reused_without_another_request(bundle, monkeypatch):
    lock, directory, package = bundle
    data = (directory / package["filename"]).read_bytes()
    (directory / package["filename"]).unlink()
    requests = []

    class Response(io.BytesIO):
        def geturl(self):
            return package["url"]

    def fetch(url, *, timeout):
        requests.append((url, timeout))
        return Response(data)

    monkeypatch.setattr(deps, "urlopen", fetch)
    deps.download(directory, deps.load_lock(lock))
    deps.download(directory, deps.load_lock(lock))
    assert requests == [(package["url"], 20)]
    assert (directory / package["filename"]).stat().st_mode & 0o777 == 0o644


def test_download_corruption_never_enters_artifact(bundle, monkeypatch):
    lock, directory, package = bundle
    (directory / package["filename"]).unlink()

    class Response(io.BytesIO):
        def geturl(self):
            return package["url"]

    monkeypatch.setattr(deps, "urlopen", lambda *a, **kw: Response(b"corrupt package"))
    with pytest.raises(ValueError):
        deps.download(directory, deps.load_lock(lock))
    assert list(directory.iterdir()) == []


@pytest.mark.parametrize("damage", ["content", "missing", "extra", "symlink"])
def test_install_rejects_bad_bundle_before_running_any_command(bundle, monkeypatch, damage):
    lock, directory, package = bundle
    path = directory / package["filename"]
    if damage == "content":
        path.write_bytes(b"modified Ubuntu package")
    elif damage == "missing":
        path.unlink()
    elif damage == "extra":
        (directory / "unreviewed.deb").write_bytes(b"extra package")
    else:
        original = directory.parent / "outside.deb"
        path.rename(original)
        path.symlink_to(original)
    monkeypatch.setattr(deps.subprocess, "run", lambda *a, **kw: pytest.fail("unverified code ran"))
    with pytest.raises(ValueError):
        deps.install(directory, deps.load_lock(lock))


@pytest.mark.parametrize("filename", ["../escape.deb", "/tmp/escape.deb", "-option.deb"])
def test_lock_rejects_unsafe_package_filenames(bundle, filename):
    lock, _, _ = bundle
    data = json.loads(lock.read_text())
    data["packages"][0]["filename"] = filename
    lock.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        deps.load_lock(lock)


def test_lock_rejects_untrusted_sources_and_duplicate_files(bundle):
    lock, _, _ = bundle
    data = json.loads(lock.read_text())
    data["packages"][0]["url"] = "https://example.org/ffmpeg.deb"
    lock.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        deps.load_lock(lock)
    data["packages"][0]["url"] = "https://archive.ubuntu.com/ubuntu/pool/test.deb"
    data["packages"].append(data["packages"][0])
    lock.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        deps.load_lock(lock)
