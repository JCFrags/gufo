#!/usr/bin/env python3
"""Exercise CDN integrity and the privileged relay's opaque-copy boundary."""

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
import zipfile

SPEC = importlib.util.spec_from_file_location(
    'devlab_cdn', Path(__file__).resolve().parents[2] / 'tools/ci/devlab_cdn.py')
cdn = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cdn)


class CDNTest(unittest.TestCase):
    def test_missing_digest_rejected(self):
        for value in (None, '', 'sha256:abc', 'md5:' + 'a' * 64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cdn.checked_digest(value)

    def test_tampered_download_rejected_before_unpack(self):
        github = Mock()
        github.repository = 'gufo-org/gufo'
        github.api.return_value = {'assets': [{'name': 'linux-artifacts.zip', 'state': 'uploaded'}]}
        artifact = {'digest': 'sha256:' + hashlib.sha256(b'original').hexdigest()}
        def download(url, path):
            path.write_bytes(b'tampered')
        with patch.object(cdn, 'wait_artifact', return_value=artifact), \
             patch.object(cdn, 'transfer', side_effect=download), \
             patch.object(cdn, 'extract_bundle') as extract:
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                cdn.download(github, 123, 2, Path('unused'))
            extract.assert_not_called()

    def test_partial_probe_still_measures_rate(self):
        result = Mock(stdout='206 1048576 12.0', returncode=28)
        with patch.object(cdn.subprocess, 'run', return_value=result):
            self.assertAlmostEqual(cdn.probe_route('https://example.org/bundle'), 1048576 / 12)

    def test_fast_direct_route_does_not_start_warp(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'bundle'
            def fetch(command, **kwargs):
                output.write_bytes(b'fixture')
                self.assertNotIn('--proxy', command)
            with patch.object(cdn, 'probe_route', return_value=10 * 1024 * 1024), \
                 patch.object(cdn, 'warp_proxy') as warp, \
                 patch.object(cdn.subprocess, 'run', side_effect=fetch):
                cdn.transfer('https://example.org/bundle', output)
            warp.assert_not_called()

    def test_slow_direct_route_uses_faster_warp_and_stops_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'bundle'
            proxy = MagicMock()
            proxy.__enter__.return_value = 'http://127.0.0.1:18080'
            def fetch(command, **kwargs):
                output.write_bytes(b'fixture')
                self.assertIn('--proxy', command)
                self.assertIn('http://127.0.0.1:18080', command)
            with patch.object(cdn, 'probe_route', side_effect=[50 * 1024, 5 * 1024 * 1024]), \
                 patch.object(cdn, 'warp_proxy', return_value=proxy), \
                 patch.object(cdn.subprocess, 'run', side_effect=fetch):
                cdn.transfer('https://example.org/bundle', output)
            proxy.__exit__.assert_called_once()

    def test_warp_unavailable_falls_back_to_direct(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'bundle'
            def fetch(command, **kwargs):
                output.write_bytes(b'fixture')
                self.assertNotIn('--proxy', command)
            with patch.object(cdn, 'probe_route', return_value=1024 * 1024), \
                 patch.object(cdn, 'warp_proxy', side_effect=RuntimeError('UDP blocked')), \
                 patch.object(cdn.subprocess, 'run', side_effect=fetch):
                cdn.transfer('https://example.org/bundle', output)

    def test_extract_only_expected_member(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'bundle.zip'
            output = Path(directory) / 'bundle.tar.gz'
            for name in ('../../escape', 'linux-artifacts.tar.gz'):
                with zipfile.ZipFile(archive, 'w') as source:
                    source.writestr(name, b'payload')
                if name.startswith('..'):
                    with self.assertRaisesRegex(ValueError, 'Unexpected'):
                        cdn.extract_bundle(archive, output)
                    self.assertFalse(output.exists())
                else:
                    cdn.extract_bundle(archive, output)
                    self.assertEqual(output.read_bytes(), b'payload')

    def test_wrong_workflow_and_superseded_attempt_rejected(self):
        for path, attempt in (('.github/workflows/ci.yml', 2),
                              ('.github/workflows/devlab-smoke.yml', 3)):
            github = Mock()
            github.api.return_value = {'path': path, 'run_attempt': attempt}
            with self.subTest(path=path, attempt=attempt), self.assertRaises(ValueError):
                cdn.wait_artifact(github, 123, 2, cdn.time.monotonic() + 10)
            github.artifacts.assert_not_called()

    def test_cleanup_preserves_product_releases_and_recent_bundles(self):
        github = Mock()
        old = '2020-01-01T00:00:00Z'
        recent = cdn.datetime.now(cdn.timezone.utc).isoformat()
        github.api.side_effect = [[
            {'id': 1, 'tag_name': 'v1.2.3', 'prerelease': True, 'created_at': old},
            {'id': 2, 'tag_name': 'ci-devlab-12-1', 'prerelease': True, 'created_at': old},
            {'id': 3, 'tag_name': 'ci-devlab-13-1', 'prerelease': True, 'created_at': recent},
            {'id': 4, 'tag_name': 'ci-devlab-14-1', 'prerelease': False, 'created_at': old},
        ], [], None, None]
        cdn.cleanup(github)
        deletions = [call.args[0] for call in github.api.call_args_list
                     if call.kwargs.get('method') == 'DELETE']
        self.assertEqual(deletions, ['/releases/2', '/git/refs/tags/ci-devlab-12-1'])

    def test_relay_copies_bytes_without_extracting_or_executing(self):
        github = Mock()
        github.repository = 'gufo-org/gufo'
        github.api.side_effect = [None, {'assets': []}]
        payload = b'opaque artifact; deliberately not a valid ZIP'
        artifact = {'id': 42, 'digest': 'sha256:' + hashlib.sha256(payload).hexdigest()}
        commands = []
        def execute(command, **kwargs):
            commands.append(command)
            if 'stdout' in kwargs:
                kwargs['stdout'].write(payload)
        with patch.object(cdn, 'wait_artifact', return_value=artifact), \
             patch.object(cdn.subprocess, 'run', side_effect=execute), \
             patch.dict(cdn.os.environ, {'GITHUB_SHA': 'a' * 40}), \
             patch.object(cdn, 'extract_bundle') as extract:
            cdn.relay(github, 123, 2)
            extract.assert_not_called()
        self.assertEqual([command[:3] for command in commands],
                         [['gh', 'api', 'repos/gufo-org/gufo/actions/artifacts/42/zip'],
                          ['gh', 'release', 'upload']])
        create = github.api.call_args_list[1]
        self.assertTrue(create.args[1]['prerelease'])
        self.assertEqual(create.args[1]['make_latest'], 'false')
        self.assertEqual(create.args[1]['target_commitish'], 'a' * 40)


if __name__ == '__main__':
    unittest.main()
