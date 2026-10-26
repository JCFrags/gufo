#!/usr/bin/env python3
"""Check artifact rejection before any runtime import or substitution."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'linux_artifact', Path(__file__).resolve().parents[2] / 'tools/ci/linux_artifact.py')
artifact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifact)


class ArtifactTest(unittest.TestCase):
    def test_old_nix_aborts_without_json_at_first_cache_miss(self):
        present = '/nix/store/cached-runtime'
        absent = '/nix/store/missing-runtime'
        responses = [subprocess.CompletedProcess([], 1, stdout='',
                     stderr=f"error: path '{absent}' is not valid"),
                     subprocess.CompletedProcess([], 0, stdout=json.dumps({
                         present: {'narHash': 'sha256-example'}}), stderr='')]
        with patch.object(artifact.subprocess, 'run', side_effect=responses) as run:
            self.assertEqual(artifact.cached_paths('https://cache.example', {present, absent}), {present})
            self.assertNotIn(absent, run.call_args.args[0])

    def test_cache_miss_exit_code_keeps_valid_partial_results(self):
        response = subprocess.CompletedProcess([], 1, stdout=json.dumps({
            '/nix/store/cached-runtime': {'narHash': 'sha256-example'},
            '/nix/store/missing-runtime': None,
        }), stderr='path is not valid')
        with patch.object(artifact.subprocess, 'run', return_value=response):
            self.assertEqual(artifact.cached_paths('https://cache.example', {
                '/nix/store/cached-runtime', '/nix/store/missing-runtime'}),
                {'/nix/store/cached-runtime'})

    def fixture(self, directory):
        root = Path(directory)
        (root / 'package.nar.gz').write_bytes(b'archive')
        manifest = {'schema': 1, 'revision': 'a' * 40,
                    'package': '/nix/store/' + 'b' * 32 + '-gufo',
                    'sha256': hashlib.sha256(b'archive').hexdigest(), 'runtime': []}
        return root, manifest

    def reject(self, root, manifest, revision, message):
        (root / 'manifest.json').write_text(json.dumps(manifest))
        with patch.object(artifact.subprocess, 'run') as run, \
                patch.object(artifact.subprocess, 'Popen') as process:
            with self.assertRaisesRegex(ValueError, message):
                artifact.restore(root, revision)
            run.assert_not_called()
            process.assert_not_called()

    def test_wrong_revision_never_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.fixture(directory)
            self.reject(root, manifest, 'c' * 40, 'authorized revision')

    def test_tampered_archive_never_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.fixture(directory)
            (root / 'package.nar.gz').write_bytes(b'tampered')
            self.reject(root, manifest, 'a' * 40, 'checksum mismatch')

    def test_runtime_derivation_cannot_trigger_a_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.fixture(directory)
            manifest['runtime'] = ['/nix/store/' + 'c' * 32 + '-runtime.drv']
            self.reject(root, manifest, 'a' * 40, 'invalid runtime output path')

    def test_package_derivation_cannot_trigger_a_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest = self.fixture(directory)
            manifest['package'] += '.drv'
            self.reject(root, manifest, 'a' * 40, 'invalid runtime output path')


if __name__ == '__main__':
    unittest.main()
