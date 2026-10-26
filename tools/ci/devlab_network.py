#!/usr/bin/env python3
"""Bounded, repeatable route measurements on the actual Devlab runners."""

import argparse
import json
import os
from pathlib import Path
import platform
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from devlab_cdn import probe_route, warp_proxy


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def artifact_url(repository, artifact):
    request = Request(f'https://api.github.com/repos/{repository}/actions/artifacts/{artifact}/zip',
                      headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN']})
    try:
        build_opener(NoRedirect).open(request, timeout=30)
    except HTTPError as error:
        if error.code == 302:
            return error.headers['Location']
        raise
    raise RuntimeError('Expected an artifact download redirect')


def measure(repository, artifact, release):
    results = {'runner': os.environ.get('RUNNER_NAME'), 'platform': platform.system(),
               'artifact': artifact, 'routes': [], 'warp_error': None}
    def sample(name, proxy=None):
        # Refresh signed URLs; credentials and query strings never reach retained output.
        url = artifact_url(repository, artifact) if name == 'actions' else release
        speed = probe_route(url, proxy)
        entry = {'source': name, 'warp': proxy is not None, 'bytes_per_second': speed}
        results['routes'].append(entry)
        print(json.dumps(entry), flush=True)
    for name in ('actions', 'release'):
        sample(name)
    with tempfile.TemporaryDirectory() as directory:
        started = time.monotonic()
        try:
            with warp_proxy(Path(directory)) as proxy:
                results['warp_setup_seconds'] = time.monotonic() - started
                # Reverse the order on the second pass to expose route/time variance.
                for name in ('release', 'actions', 'actions', 'release'):
                    sample(name, proxy)
        except Exception as error:
            results['warp_error'] = type(error).__name__ + ': ' + str(error)
            print('WARP setup/probe failed: ' + results['warp_error'], flush=True)
    for name in ('release', 'actions'):
        sample(name)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=int, required=True)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    result = measure(os.environ['GITHUB_REPOSITORY'], args.artifact, args.release)
    Path('network-probe.json').write_text(json.dumps(result, indent=2) + '\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
        summary.write('### Devlab network probe\n\n```json\n' + json.dumps(result, indent=2) + '\n```\n')


if __name__ == '__main__':
    main()
