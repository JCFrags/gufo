#!/usr/bin/env python3
"""Report which Hugging Face route and cache a Devlab runner's downloads use.

Prints the runner's Hugging Face settings as huggingface_hub resolves them,
whether the pinned model files are already in the persistent cache, and the
time-to-first-byte and throughput of bounded reads of the same files through
the resolved endpoint and directly from huggingface.co.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from huggingface_hub import constants, hf_hub_url

DIRECT = 'https://huggingface.co'
# Pinned files the Devlab jobs fetch: large shards show mirror warmth, and the
# small model shows whether files fetched earlier today are served locally.
PROBES = [
    ('flash-next', 'UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00002-of-00004.gguf'),
    ('qwen27', 'Qwen3.8-27B-UD-Q4_K_XL.gguf'),
    ('embedding', 'model.safetensors'),
]
HEADERS = ('server', 'via', 'age', 'x-cache', 'x-cache-status', 'cache-control',
           'x-served-by', 'x-linked-size', 'x-xet-hash', 'content-length', 'content-range')
ENVIRONMENT = ('HF_ENDPOINT', 'HF_HUB_DISABLE_XET', 'HF_HOME', 'HF_HUB_CACHE',
               'HF_XET_HIGH_PERFORMANCE', 'HF_HUB_ENABLE_HF_TRANSFER', 'HF_HUB_OFFLINE')


def location(url):
    # Signed CDN URLs carry credentials in the query; keep only scheme, host and path.
    parts = urlsplit(url)
    return f'{parts.scheme}://{parts.netloc}{parts.path}'


class Trace(HTTPRedirectHandler):
    def __init__(self):
        self.hops = []

    def redirect_request(self, request, fp, code, message, headers, newurl):
        self.hops.append({'status': code, 'to': location(newurl)})
        return super().redirect_request(request, fp, code, message, headers, newurl)


def read(url, limit, timeout):
    trace = Trace()
    started = time.monotonic()
    result = {'url': location(url)}
    try:
        with build_opener(trace).open(Request(url, headers={'User-Agent': 'gufo-devlab-hf-probe'}),
                                      timeout=timeout) as response:
            first = response.read(1 << 20)
            result['ttfb_seconds'] = round(time.monotonic() - started, 3)
            result['status'] = response.status
            result['final'] = location(response.url)
            result['headers'] = {name: response.headers[name] for name in HEADERS if name in response.headers}
            received = len(first)
            body_started = time.monotonic()
            while received < limit and time.monotonic() - started < timeout:
                chunk = response.read(min(8 << 20, limit - received))
                if not chunk:
                    break
                received += len(chunk)
            seconds = time.monotonic() - body_started
            result['bytes'] = received
            result['mib_per_second'] = round(received / 2**20 / seconds, 1) if seconds > 0 else None
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    result['redirects'] = trace.hops
    result['seconds'] = round(time.monotonic() - started, 3)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, default=Path('tests/functional/devlab.json'))
    parser.add_argument('--limit-mib', type=int, default=1024)
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--output', type=Path, default=Path('hf-probe.json'))
    args = parser.parse_args()
    assets = json.loads(args.registry.read_text())['assets']
    home = Path(constants.HF_HOME)
    report = {
        'runner': os.environ.get('RUNNER_NAME'),
        'platform': platform.system(),
        'environment': {name: os.environ.get(name) for name in ENVIRONMENT},
        'proxy_set': {name: bool(os.environ.get(name)) for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY')},
        'resolved': {'endpoint': constants.ENDPOINT, 'disable_xet': constants.HF_HUB_DISABLE_XET,
                     'hf_home': str(home)},
        'files': [],
    }
    print(json.dumps({key: report[key] for key in ('runner', 'environment', 'proxy_set', 'resolved')}, indent=2),
          flush=True)
    limit = args.limit_mib << 20
    for key, name in PROBES:
        asset = assets[key]
        cached = home / 'gufo' / 'models' / key / asset['revision'] / name
        entry = {'asset': key, 'file': name,
                 'persistent_cache': cached.stat().st_size if cached.is_file() else None}
        resolved = hf_hub_url(asset['repo'], name, revision=asset['revision'])
        direct = hf_hub_url(asset['repo'], name, revision=asset['revision'], endpoint=DIRECT)
        # Two endpoint reads expose a cold mirror (slow first byte) filling, then a
        # direct read gives the same host's internet baseline.
        entry['reads'] = [dict(read(resolved, limit, args.timeout), route='resolved', attempt=1),
                          dict(read(resolved, limit, args.timeout), route='resolved', attempt=2)]
        if location(resolved) != location(direct):
            entry['reads'].append(dict(read(direct, limit, args.timeout), route='direct', attempt=1))
        for item in entry['reads']:
            print(json.dumps(dict(item, asset=key)), flush=True)
        report['files'].append(entry)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as handle:
            handle.write('### Hugging Face route probe\n\n')
            handle.write(f"Runner `{report['runner']}`; endpoint `{constants.ENDPOINT}`; "
                         f"Xet disabled `{constants.HF_HUB_DISABLE_XET}`; HF_HOME `{home}`.\n\n")
            handle.write('| Asset | Persistent cache | Route | TTFB s | MiB/s | Final host | Error |\n')
            handle.write('|---|---|---|---|---|---|---|\n')
            for entry in report['files']:
                for item in entry['reads']:
                    host = urlsplit(item.get('final', item['url'])).netloc
                    handle.write(f"| {entry['asset']} | {entry['persistent_cache']} | {item['route']} #{item['attempt']} "
                                 f"| {item.get('ttfb_seconds', '')} | {item.get('mib_per_second', '')} | {host} "
                                 f"| {item.get('error', '')} |\n")


if __name__ == '__main__':
    main()
