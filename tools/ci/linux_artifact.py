#!/usr/bin/env python3
"""Transfer pinned Linux packages to GPU runners without building on them."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


CACHES = ('https://cache.nixos.org', 'https://gufo.cachix.org')


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def cached_paths(cache, paths):
    # Older Nix aborts a batch at its first missing path without emitting JSON;
    # newer Nix includes null entries. Retry the remaining paths on old Nix.
    pending = set(paths)
    while pending:
        result = subprocess.run(['nix', 'path-info', '--store', cache, '--json', *sorted(pending)],
                                capture_output=True, text=True, check=False)
        try:
            info = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            absent = set(re.findall(r"path '(/nix/store/[^']+)' is not valid", result.stderr)) & pending
            if not absent:
                raise RuntimeError(f'Cannot query {cache}: {result.stderr}') from error
            pending -= absent
            continue
        return {path for path, value in info.items() if value is not None}
    return set()


def pack(package, revision, destination):
    package = package.resolve(strict=True)
    version = output(str(package / 'bin/gufo'), '--version')
    if not version.endswith(f'({revision[:7]})'):
        raise ValueError(f'Package revision mismatch: {version}; expected {revision}')
    closure = output('nix-store', '--query', '--requisites', str(package)).splitlines()
    runtime = set(closure) - {str(package)}
    missing = set(runtime)
    for cache in CACHES:
        if missing:
            missing -= cached_paths(cache, missing)
    # Normal artifacts carry just Gufo; runtimes come from signed public caches.
    # If a PR introduces an uncached runtime, carry the complete closure instead
    # so fork PRs never need cache credentials or a build on the GPU runner.
    exported = closure if missing else [str(package)]
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination / 'package.nar.gz'
    with subprocess.Popen(['nix-store', '--export', *exported], stdout=subprocess.PIPE) as process:
        with gzip.open(archive, 'wb', compresslevel=1) as compressed:
            shutil.copyfileobj(process.stdout, compressed)
        if process.wait():
            raise RuntimeError('Cannot export the Linux package')
    with archive.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    manifest = {'schema': 1, 'revision': revision, 'package': str(package), 'version': version,
                'sha256': digest, 'runtime': [] if missing else sorted(runtime)}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{version}: {archive.stat().st_size / 2**20:.1f} MiB artifact; '
          f'{len(manifest["runtime"])} runtime paths from public caches', flush=True)


def restore(source, revision):
    manifest = json.loads((source / 'manifest.json').read_text())
    if manifest['schema'] != 1 or manifest['revision'] != revision:
        raise ValueError('Artifact does not match the authorized revision')
    archive = source / 'package.nar.gz'
    with archive.open('rb') as file:
        if hashlib.file_digest(file, 'sha256').hexdigest() != manifest['sha256']:
            raise ValueError('Linux package archive checksum mismatch')
    # These are output paths, never .drv files: Nix can only substitute them.
    paths = [manifest['package'], *manifest['runtime']]
    if any(not re.fullmatch(r'/nix/store/[a-z0-9]{32}-[^/\s]+', path) or path.endswith('.drv')
           for path in paths):
        raise ValueError('Artifact contains an invalid runtime output path')
    if manifest['runtime']:
        subprocess.run(['nix-store', '--realise', '--option', 'fallback', 'false',
                        *manifest['runtime']], check=True, stdout=subprocess.DEVNULL)
    with subprocess.Popen(['nix-store', '--import'], stdin=subprocess.PIPE,
                          stdout=subprocess.DEVNULL) as process:
        with gzip.open(archive, 'rb') as compressed:
            shutil.copyfileobj(compressed, process.stdin)
        process.stdin.close()
        if process.wait():
            raise RuntimeError('Cannot import the Linux package')
    package = Path(manifest['package'])
    version = output(str(package / 'bin/gufo'), '--version')
    if version != manifest['version'] or not version.endswith(f'({revision[:7]})'):
        raise ValueError('Imported Linux binary has the wrong revision')
    subprocess.run(['nix-store', '--add-root', str(source / 'package'), '--indirect',
                    '--realise', str(package)], check=True, stdout=subprocess.DEVNULL)
    print(version, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('pack')
    create.add_argument('--package', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--revision', required=True)
    extract = commands.add_parser('restore')
    extract.add_argument('--source', type=Path, required=True)
    extract.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.revision):
        parser.error('revision must be an immutable full Git commit SHA')
    if args.command == 'pack':
        pack(args.package, args.revision, args.output)
    else:
        restore(args.source.resolve(), args.revision)


if __name__ == '__main__':
    main()
