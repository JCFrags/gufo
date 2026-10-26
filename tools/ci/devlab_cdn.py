#!/usr/bin/env python3
"""Relay opaque CI artifacts to the release CDN; never unpack or execute them."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile


class GitHub:
    def __init__(self, repository):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        self.repository = repository
        self.root = f"https://api.github.com/repos/{repository}"

    def api(self, path, data=None, method=None, missing=False):
        request = Request(self.root + path, method=method,
                          data=None if data is None else json.dumps(data).encode(),
                          headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                                   "Accept": "application/vnd.github+json",
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=60) as response:
                body = response.read()
                return json.loads(body) if body else None
        except HTTPError as error:
            if missing and error.code == 404:
                return None
            raise

    def artifacts(self, run, name):
        # Filtering by name avoids pagination through unrelated model results.
        return self.api(f"/actions/runs/{run}/artifacts?name={name}")["artifacts"]


def checked_digest(value):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value or ""):
        raise ValueError("Missing or invalid GitHub artifact SHA-256")
    return value[7:]


def verify(path, digest):
    expected = checked_digest(digest)
    with Path(path).open("rb") as source:
        checksum = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
        actual = checksum.hexdigest()
    if actual != expected:
        raise ValueError("CDN bundle checksum mismatch")


def tag_for(run, attempt):
    return f"ci-devlab-{run}-{attempt}"


def wait_artifact(github, run, attempt, deadline):
    name = f"linux-devlab-{attempt}"
    while time.monotonic() < deadline:
        state = github.api(f"/actions/runs/{run}")
        if state["path"] != ".github/workflows/devlab-smoke.yml":
            raise ValueError("Source must be the Devlab functional workflow")
        if state["run_attempt"] != attempt:
            raise ValueError("Source run was superseded by another attempt")
        artifacts = [item for item in github.artifacts(run, name)
                     if item["name"] == name and not item["expired"]]
        if len(artifacts) == 1:
            checked_digest(artifacts[0].get("digest"))
            return artifacts[0]
        if state["status"] == "completed":
            raise RuntimeError("Source run finished without the Linux bundle")
        jobs = github.api(f"/actions/runs/{run}/attempts/{attempt}/jobs?per_page=100")["jobs"]
        if any(job["name"].startswith("Hosted Linux binaries /") and
               job["conclusion"] in ("failure", "cancelled", "timed_out", "skipped")
               for job in jobs):
            raise RuntimeError("Hosted Linux build failed")
        print("Waiting for hosted Linux bundle", flush=True)
        time.sleep(10)
    raise TimeoutError("Timed out waiting for hosted Linux bundle")


def relay(github, run, attempt):
    artifact = wait_artifact(github, run, attempt, time.monotonic() + 7200)
    tag = tag_for(run, attempt)
    with tempfile.TemporaryDirectory() as directory:
        bundle = Path(directory) / "linux-artifacts.zip"
        # gh handles the authenticated API redirect without logging signed URLs.
        with bundle.open("wb") as output:
            subprocess.run(["gh", "api", f"repos/{github.repository}/actions/artifacts/{artifact['id']}/zip"],
                           stdout=output, check=True)
        verify(bundle, artifact["digest"])
        release = github.api(f"/releases/tags/{tag}", missing=True)
        if release is None:
            release = github.api("/releases", {
                "tag_name": tag, "target_commitish": os.environ["GITHUB_SHA"],
                "name": f"Temporary Devlab bundle {run}/{attempt}",
                "body": "Untrusted CI binaries for Devlab. Automatically removed after three days.",
                "prerelease": True, "make_latest": "false"})
        assets = [asset for asset in release["assets"] if asset["name"] == bundle.name]
        if assets:
            if assets[0].get("digest") != artifact["digest"]:
                raise ValueError("Existing CDN asset has a different checksum")
        else:
            subprocess.run(["gh", "release", "upload", tag, str(bundle),
                            "--repo", github.repository], check=True)
        print(f"CDN bundle ready: {tag}; {artifact['digest']}", flush=True)


def extract_bundle(source, destination):
    # Never extract arbitrary artifact paths. The single member is copied to a fixed path.
    with zipfile.ZipFile(source) as archive:
        if archive.namelist() != ["linux-artifacts.tar.gz"]:
            raise ValueError("Unexpected Linux artifact ZIP contents")
        with archive.open("linux-artifacts.tar.gz") as data, Path(destination).open("wb") as output:
            shutil.copyfileobj(data, output)


def probe_route(url, proxy=None):
    command = ["curl", "--silent", "--location", "--fail", "--max-time", "12",
               "--range", "0-2097151", "--output", os.devnull,
               "--proto", "=https", "--proto-redir", "=https",
               "--write-out", "%{http_code} %{size_download} %{time_total}"]
    if proxy:
        command += ["--proxy", proxy]
    result = subprocess.run(command + [url], capture_output=True, text=True, timeout=20)
    try:
        status, size, elapsed = result.stdout.split()
        speed = int(size) / max(float(elapsed), 0.001) if status == "206" else 0
    except (ValueError, ZeroDivisionError):
        speed = 0
    # Partial ranges are useful measurements even when curl's time limit expires.
    print(f"{'WARP' if proxy else 'Direct'} route: {speed / 1024:.0f} KiB/s", flush=True)
    return speed


@contextmanager
def warp_proxy(directory):
    version = "4.2.1"
    archive = directory / "usque.zip"
    url = ("https://github.com/Diniboy1123/usque/releases/download/"
           f"v{version}/usque_{version}_{'windows' if os.name == 'nt' else 'linux'}_amd64.zip")
    subprocess.run(["curl", "--silent", "--show-error", "--fail", "--location",
                    "--max-time", "120", "--proto", "=https", "--proto-redir", "=https",
                    "--output", str(archive), url], check=True, timeout=130)
    digest = ("f6f7f0a1a2bc9bcc15cf563ec1f892d00690a92c086b23ed3211b802209099e7"
              if os.name == "nt" else
              "4117e20695078af9c11edecd1a826c009bbc7ea0b7f64458612b4198910bc313")
    verify(archive, "sha256:" + digest)
    executable = directory / ("usque.exe" if os.name == "nt" else "usque")
    with zipfile.ZipFile(archive) as source, source.open(executable.name) as data, executable.open("wb") as output:
        shutil.copyfileobj(data, output)
    executable.chmod(0o700)
    config = directory / "warp.json"
    command = [str(executable), "--config", str(config)]
    with (directory / "warp.log").open("wb") as log:
        # Credentials remain in the private temporary directory, never in CI logs.
        subprocess.run(command + ["register", "--accept-tos"], stdout=log, stderr=log,
                       check=True, timeout=30)
        config.chmod(0o600)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        process = subprocess.Popen(command + ["l4-http-proxy", "--bind", "127.0.0.1",
                                             "--port", str(port), "--system-dns"],
                                   stdout=log, stderr=log)
        try:
            proxy = f"http://127.0.0.1:{port}"
            ready = False
            for _ in range(5):
                trace = subprocess.run(["curl", "--silent", "--fail", "--max-time", "5",
                                        "--proxy", proxy, "https://www.cloudflare.com/cdn-cgi/trace"],
                                       capture_output=True, text=True, timeout=10)
                if trace.returncode == 0 and "warp=on" in trace.stdout.splitlines():
                    ready = True
                    break
                if process.poll() is not None:
                    break
                time.sleep(1)
            if not ready:
                raise RuntimeError("WARP proxy did not become ready")
            yield proxy
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def transfer(url, bundle):
    def fetch(proxy=None):
        command = ["curl", "--fail", "--location", "--retry", "2",
                   "--connect-timeout", "20", "--max-time", "900",
                   "--speed-limit", "131072", "--speed-time", "60",
                   "--proto", "=https", "--proto-redir", "=https",
                   "--output", str(bundle)]
        if proxy:
            command += ["--proxy", proxy]
        started = time.monotonic()
        subprocess.run(command + [url], check=True)
        print(f"Binary transfer: {bundle.stat().st_size / 1024 / 1024:.1f} MiB in "
              f"{time.monotonic() - started:.1f}s ({'WARP' if proxy else 'direct'})", flush=True)

    direct = probe_route(url)
    # Avoid registration and tunnel setup when the direct route is already fast.
    if direct >= 5 * 1024 * 1024:
        fetch()
        return
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        try:
            with warp_proxy(directory) as proxy:
                tunneled = probe_route(url, proxy)
                if tunneled > max(direct * 1.25, 128 * 1024):
                    print("Selected WARP for binary download", flush=True)
                    fetch(proxy)
                    return
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
            print(f"WARP unavailable ({type(error).__name__}); using direct route", flush=True)
    print("Selected direct route for binary download", flush=True)
    fetch()


def download(github, run, attempt, output):
    deadline = time.monotonic() + 7200
    artifact = wait_artifact(github, run, attempt, deadline)
    tag = tag_for(run, attempt)
    deadline = min(deadline, time.monotonic() + 600)
    while time.monotonic() < deadline:
        release = github.api(f"/releases/tags/{tag}", missing=True)
        assets = [] if release is None else [asset for asset in release["assets"]
                   if asset["name"] == "linux-artifacts.zip" and asset["state"] == "uploaded"]
        if assets:
            # Construct the URL ourselves; do not follow an artifact-supplied URL.
            url = f"https://github.com/{github.repository}/releases/download/{tag}/linux-artifacts.zip"
            with tempfile.TemporaryDirectory() as directory:
                bundle = Path(directory) / "bundle.zip"
                transfer(url, bundle)
                verify(bundle, artifact["digest"])
                extract_bundle(bundle, output)
            print("Release CDN bundle downloaded and SHA-256 verified", flush=True)
            return
        state = github.api(f"/actions/runs/{run}")
        if state["run_attempt"] != attempt or state["status"] == "completed":
            raise RuntimeError("Source run ended before CDN delivery")
        print("Waiting for release CDN relay; model downloads continue", flush=True)
        time.sleep(10)
    raise TimeoutError("CDN relay unavailable; install devlab-cdn.yml on the default branch")


def cleanup(github):
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    stale = []
    page = 1
    while True:
        releases = github.api(f"/releases?per_page=100&page={page}")
        if not releases:
            break
        for release in releases:
            if (re.fullmatch(r"ci-devlab-[0-9]+-[0-9]+", release["tag_name"]) and
                    release["prerelease"] and
                    datetime.fromisoformat(release["created_at"].replace("Z", "+00:00")) < cutoff):
                stale.append(release)
        page += 1
    for release in stale:
        github.api(f"/releases/{release['id']}", method="DELETE")
        github.api(f"/git/refs/tags/{release['tag_name']}", method="DELETE", missing=True)
        print(f"Removed expired Devlab bundle {release['tag_name']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("relay", "download", "cleanup"))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--run", type=int)
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--output", type=Path, default=Path("linux-artifacts.tar.gz"))
    args = parser.parse_args()
    github = GitHub(args.repository)
    if args.operation == "cleanup":
        cleanup(github)
    else:
        if not args.run or not args.attempt or args.run < 1 or args.attempt < 1:
            parser.error("positive --run and --attempt are required")
        if args.operation == "relay":
            relay(github, args.run, args.attempt)
        else:
            download(github, args.run, args.attempt, args.output)


if __name__ == "__main__":
    main()
