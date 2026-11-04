#!/usr/bin/env python3
"""Share pinned Ubuntu FFmpeg packages across gallery shards (readiness § CI)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

LOCK = Path(__file__).with_name("ci_gallery_ffmpeg.lock.json")
HOSTS = {"archive.ubuntu.com", "security.ubuntu.com"}


def load_lock(path: Path = LOCK) -> list[dict]:
    data = json.loads(path.read_text())
    if data.get("schema_version") != 1 or data.get("platform") != "ubuntu-24.04-amd64":
        raise ValueError("unsupported gallery dependency lock")
    packages = data["packages"]
    seen: set[str] = set()
    names: set[str] = set()
    for package in packages:
        filename, url = package["filename"], urlsplit(package["url"])
        if (
            not re.fullmatch(r"[a-z0-9][A-Za-z0-9._+%:~-]*\.deb", filename)
            or filename in seen
            or package["name"] in names
            or package["architecture"] not in {"amd64", "all"}
            or not re.fullmatch(r"[0-9a-f]{128}", package["sha512"])
            or not isinstance(package["size"], int)
            or package["size"] <= 0
            or url.scheme != "https"
            or url.netloc not in HOSTS
            or not url.path.startswith("/ubuntu/pool/")
            or url.query
            or url.fragment
        ):
            raise ValueError(f"unsafe or duplicate gallery dependency: {filename}")
        seen.add(filename)
        names.add(package["name"])
    if "ffmpeg" not in names:
        raise ValueError("gallery dependency lock must include ffmpeg")
    return packages


def verify_file(path: Path, package: dict) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != package["size"]:
        raise ValueError(f"missing, unsafe or wrong-size gallery package: {path.name}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha512").hexdigest()
    if digest != package["sha512"]:
        raise ValueError(f"gallery package digest mismatch: {path.name}")


def verify(directory: Path, packages: list[dict]) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("gallery bundle must be a real directory")
    if {p.name for p in directory.iterdir()} != {p["filename"] for p in packages}:
        raise ValueError("gallery bundle has missing or unexpected files")
    for package in packages:
        verify_file(directory / package["filename"], package)


def download(directory: Path, packages: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("gallery bundle must be a real directory")

    def fetch(package: dict) -> None:
        path = directory / package["filename"]
        if path.exists() or path.is_symlink():
            verify_file(path, package)
            return
        original = urlsplit(package["url"])
        alternate = (
            "security.ubuntu.com"
            if original.netloc == "archive.ubuntu.com"
            else "archive.ubuntu.com"
        )
        urls = [package["url"], urlunsplit(original._replace(netloc=alternate))]
        last_error: Exception | None = None
        for url in urls:
            # Partial downloads are never promoted into the cache/artifact.
            fd, name = tempfile.mkstemp(dir=directory, suffix=".partial")
            partial = Path(name)
            try:
                with os.fdopen(fd, "wb") as output, urlopen(url, timeout=20) as response:
                    final = urlsplit(response.geturl())
                    if final.scheme != "https" or final.netloc not in HOSTS:
                        raise ValueError("gallery package download redirected outside Ubuntu HTTPS")
                    remaining = package["size"]
                    deadline = time.monotonic() + 40
                    while block := response.read1(min(1024 * 1024, remaining + 1)):
                        if time.monotonic() > deadline:
                            raise TimeoutError("gallery package transfer exceeded 40 seconds")
                        remaining -= len(block)
                        if remaining < 0:
                            raise ValueError(f"oversize gallery package: {path.name}")
                        output.write(block)
                verify_file(partial, package)
                partial.chmod(0o644)
                partial.replace(path)
                return
            except (HTTPError, URLError, TimeoutError, ValueError) as error:
                last_error = error
            finally:
                partial.unlink(missing_ok=True)
        raise RuntimeError(f"cannot download pinned package {path.name}") from last_error

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch, packages))
    verify(directory, packages)
    print(f"Verified {len(packages)} pinned packages in {time.monotonic() - started:.2f}s")


def install(directory: Path, packages: list[dict]) -> None:
    # Integrity checks precede every subprocess, especially privileged dpkg.
    verify(directory, packages)
    release = Path("/etc/os-release").read_text().splitlines()
    if (
        'VERSION_ID="24.04"' not in release
        or "ID=ubuntu" not in release
        or platform.machine() != "x86_64"
    ):
        raise ValueError("gallery packages require Ubuntu 24.04 x86_64")
    subprocess.run(
        [
            "sudo",
            "env",
            "DEBIAN_FRONTEND=noninteractive",
            "dpkg",
            "--install",
            *[str(directory / p["filename"]) for p in packages],
        ],
        check=True,
        timeout=180,
    )
    version = next(p["version"] for p in packages if p["name"] == "ffmpeg")
    installed = subprocess.check_output(["dpkg-query", "-W", "-f=${Version}", "ffmpeg"], text=True)
    if installed != version:
        raise ValueError(f"unexpected installed FFmpeg version: {installed}")
    # The gallery needs a real encoder, not merely an executable on PATH.
    with tempfile.TemporaryDirectory() as temporary:
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=16x16:rate=1",
                "-frames:v",
                "1",
                "-c:v",
                "libx264",
                str(Path(temporary) / "probe.mp4"),
            ],
            check=True,
            timeout=20,
        )


def refresh_lock(path: Path) -> None:
    """Resolve reviewed runtime package names from authenticated Ubuntu indexes.

    This maintenance command does not install packages or change host APT state.
    CI only consumes the committed lock; it never resolves floating dependencies.
    """
    names = [p["name"] for p in load_lock(path)]
    with tempfile.TemporaryDirectory(prefix="xy-gallery-apt-") as temporary:
        root = Path(temporary)
        for child in ("lists/partial", "archives/partial", "sources.list.d"):
            (root / child).mkdir(parents=True, exist_ok=True)
        (root / "status").touch()
        sources = [
            ("archive.ubuntu.com", "noble"),
            ("archive.ubuntu.com", "noble-updates"),
            ("security.ubuntu.com", "noble-security"),
        ]
        (root / "sources.list").write_text(
            "".join(
                f"deb [arch=amd64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] https://{host}/ubuntu {suite} main universe\n"
                for host, suite in sources
            )
        )
        config = root / "apt.conf"
        config.write_text(f'''Dir::Etc::sourcelist "{root}/sources.list";
Dir::Etc::sourceparts "{root}/sources.list.d";
Dir::State::lists "{root}/lists";
Dir::State::status "{root}/status";
Dir::Cache::archives "{root}/archives";
Dir::Cache::pkgcache "";
Dir::Cache::srcpkgcache "";
Acquire::Languages "none";
APT::Architecture "amd64";
APT::Architectures {{ "amd64"; }};
Acquire::Retries "2";
Acquire::http::Timeout "20";
Acquire::https::Timeout "20";
Acquire::https::Verify-Peer "true";
Acquire::https::Verify-Host "true";
Acquire::Check-Valid-Until "true";
Acquire::AllowInsecureRepositories "false";
Acquire::AllowDowngradeToInsecureRepositories "false";
APT::Get::AllowUnauthenticated "false";
APT::Update::Error-Mode "any";
''')
        environment = {**os.environ, "LC_ALL": "C"}
        subprocess.run(
            ["apt-get", "-c", str(config), "update"], env=environment, check=True, timeout=300
        )
        policy = subprocess.check_output(
            ["apt-cache", "-c", str(config), "policy", *names], env=environment, text=True
        )
        versions: dict[str, str] = {}
        current = ""
        for line in policy.splitlines():
            if line and not line[0].isspace() and line.endswith(":"):
                current = line[:-1]
            if line.strip().startswith("Candidate:"):
                versions[current] = line.split("Candidate:", 1)[1].strip()
        if set(versions) != set(names) or "(none)" in versions.values():
            raise ValueError("Ubuntu indexes cannot resolve every locked package")
        uris = subprocess.check_output(
            [
                "apt-get",
                "-c",
                str(config),
                "--print-uris",
                "download",
                *[f"{name}={versions[name]}" for name in names],
            ],
            env=environment,
            text=True,
        )
        packages = []
        for line in uris.splitlines():
            if not line.startswith("'https://"):
                continue
            url, filename, size, checksum = shlex.split(line)
            algorithm, digest = checksum.split(":", 1)
            if algorithm != "SHA512":
                raise ValueError("Ubuntu package index must provide a SHA-512 digest")
            name = filename.split("_", 1)[0]
            packages.append(
                dict(
                    name=name,
                    version=versions[name],
                    architecture=filename.rsplit("_", 1)[1][:-4],
                    filename=filename,
                    size=int(size),
                    sha512=digest,
                    url=url,
                )
            )
        if {p["name"] for p in packages} != set(names):
            raise ValueError("Ubuntu indexes omitted a locked package")
        updated = {
            "schema_version": 1,
            "platform": "ubuntu-24.04-amd64",
            "source": "Ubuntu noble, noble-updates and noble-security; authenticated with ubuntu-archive-keyring",
            "packages": sorted(packages, key=lambda p: p["name"]),
        }
        staged = root / "lock.json"
        staged.write_text(json.dumps(updated, indent=2) + "\n")
        load_lock(staged)
        path.write_text(staged.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("download", "verify", "install", "refresh-lock"))
    parser.add_argument("--lock", type=Path, default=LOCK)
    parser.add_argument("--directory", type=Path, default=Path("dist/gallery-ffmpeg"))
    args = parser.parse_args()
    if args.command == "refresh-lock":
        refresh_lock(args.lock)
    else:
        {"download": download, "verify": verify, "install": install}[args.command](
            args.directory, load_lock(args.lock)
        )


if __name__ == "__main__":
    main()
