"""Tests des mises à jour avec réseau et lancement d'installateur simulés."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import autoloot_update as update


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.autoloot-owned').write_text('BetterAutoLoot-DLTB-v1')
        (self.root / 'evidence/updates').mkdir(parents=True)
        (self.root / 'runtime').mkdir()
        (self.root / 'runtime/pythonw.exe').touch()

    def test_stable_versions_only_and_numeric_order(self):
        self.assertGreater(update.version_tuple('1.10.0'), update.version_tuple('1.9.9'))
        for value in ('v1.4.0', '1.4', '1.4.0-beta', '01.4.0', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                update.version_tuple(value)

    def test_startup_then_twenty_four_hours_without_blocking(self):
        now = [10]
        scheduler = update.UpdateScheduler(self.root, clock=lambda: now[0])
        child = Mock()
        child.poll.return_value = 0
        with patch.object(update.subprocess, 'Popen', return_value=child) as spawn:
            scheduler.tick()
            now[0] += update.INTERVAL - 1
            scheduler.tick()
            self.assertEqual(spawn.call_count, 1)
            now[0] += 1
            scheduler.tick()
            self.assertEqual(spawn.call_count, 2)
            self.assertIn('--check', spawn.call_args.args[0])

    def test_existing_child_prevents_parallel_launch(self):
        scheduler = update.UpdateScheduler(self.root, clock=lambda: 100)
        scheduler.child = Mock()
        scheduler.child.poll.return_value = None
        with patch.object(update.subprocess, 'Popen') as spawn:
            scheduler.tick()
            spawn.assert_not_called()

    def test_disabled_installation_skips_updater(self):
        (self.root / '.autoloot-disabled').touch()
        with patch.object(update.subprocess, 'Popen') as spawn:
            update.UpdateScheduler(self.root).tick()
            spawn.assert_not_called()

    def test_pending_update_uses_cache_and_retries_after_game_exit(self):
        update.write_state(self.root, {'pending': '9.0.0'})
        scheduler = update.UpdateScheduler(self.root, clock=lambda: 100)
        scheduler.next_check = 1000
        with patch.object(update.subprocess, 'Popen') as spawn:
            scheduler.tick()
            self.assertNotIn('--check', spawn.call_args.args[0])

    def test_network_failure_persists_error_without_propagating(self):
        with patch.object(update, 'check_release', side_effect=OSError('offline')):
            update.run(self.root, True)
        state = update.read_state(self.root)
        self.assertEqual(state['status'], 'error')
        self.assertIn('offline', state['error'])
        self.assertGreater(state['last_checked'], 0)

    def test_game_running_prevents_download_and_installer(self):
        directory = self.root / 'evidence/updates'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'manifest.json').write_bytes(b'{}')
        (directory / 'manifest.sig').write_bytes(b'sig')
        manifest = {'version': '9.0.0', 'filename': 'BetterAutoLoot-Setup-9.0.0.exe'}
        with patch('update_trust.verify_manifest', return_value=manifest), patch.object(update, 'game_running', return_value=True), patch.object(update, 'download') as download, patch.object(update.subprocess, 'Popen') as spawn:
            update.install_pending(self.root, {'pending': '9.0.0'})
            download.assert_not_called()
            spawn.assert_not_called()

    def test_install_rechecks_game_and_launches_verified_payload_silently(self):
        import hashlib
        directory = self.root / 'evidence/updates'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'manifest.json').write_bytes(b'{}')
        (directory / 'manifest.sig').write_bytes(b'sig')
        payload = b'owned disposable installer fixture'
        manifest = {'version': '9.0.0', 'filename': 'BetterAutoLoot-Setup-9.0.0.exe',
                    'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
        state = {'pending': '9.0.0'}
        with patch('update_trust.verify_manifest', return_value=manifest), patch.object(update, 'game_running', side_effect=[False, True]), patch.object(update, 'download', return_value=payload), patch.object(update.subprocess, 'Popen') as spawn:
            update.install_pending(self.root, state)
            spawn.assert_not_called()
            self.assertNotIn('install_attempt', state)
        with patch('update_trust.verify_manifest', return_value=manifest), patch.object(update, 'game_running', return_value=False), patch.object(update.subprocess, 'Popen') as spawn:
            update.install_pending(self.root, state)
            command = spawn.call_args.args[0]
            self.assertIn('/VERYSILENT', command)
            self.assertIn('/DIR=' + str(self.root), command)
            self.assertEqual(state['install_attempt'], '9.0.0')
            spawn.reset_mock()
            update.install_pending(self.root, state)
            spawn.assert_not_called()

    def test_update_lock_excludes_second_helper(self):
        with update.UpdateLock(self.root) as first:
            self.assertTrue(first)
            with update.UpdateLock(self.root) as second:
                self.assertFalse(second)
        with update.UpdateLock(self.root) as later:
            self.assertTrue(later)

    def pending_fixture(self):
        import hashlib
        directory = self.root / 'evidence/updates'
        (directory / 'manifest.json').write_bytes(b'{}')
        (directory / 'manifest.sig').write_bytes(b'sig')
        payload = b'owned installer test payload'
        manifest = {'version': '9.0.0', 'filename': 'BetterAutoLoot-Setup-9.0.0.exe',
                    'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
        return manifest, payload, directory / manifest['filename']

    def test_corrupt_cached_installer_is_replaced_with_verified_download(self):
        manifest, payload, installer = self.pending_fixture()
        installer.write_bytes(b'corrupted cache')
        with patch('update_trust.verify_manifest', return_value=manifest), patch.object(update, 'game_running', return_value=False), patch.object(update, 'download', return_value=payload) as download, patch.object(update.subprocess, 'Popen') as spawn:
            update.install_pending(self.root, {'pending': '9.0.0'})
        self.assertEqual(installer.read_bytes(), payload)
        download.assert_called_once()
        spawn.assert_called_once()

    def test_failed_pending_download_has_persisted_backoff(self):
        manifest, _, _ = self.pending_fixture()
        update.write_state(self.root, {'pending': '9.0.0'})
        with patch('update_trust.verify_manifest', return_value=manifest), patch.object(update, 'game_running', return_value=False), patch.object(update, 'download', side_effect=OSError('offline')) as download:
            update.run(self.root, False)
            update.run(self.root, False)
        download.assert_called_once()
        self.assertGreater(update.read_state(self.root)['retry_after'], 0)

    def test_uninstall_during_download_cancels_launch_and_state_recreation(self):
        manifest, payload, _ = self.pending_fixture()
        def download(*ignored):
            (self.root / '.autoloot-owned').unlink()
            return payload
        with patch('update_trust.verify_manifest', return_value=manifest), patch.object(update, 'game_running', return_value=False), patch.object(update, 'download', side_effect=download), patch.object(update.subprocess, 'Popen') as spawn:
            update.install_pending(self.root, {'pending': '9.0.0'})
            spawn.assert_not_called()
        import shutil
        shutil.rmtree(self.root / 'evidence')
        update.write_state(self.root, {'status': 'late result'})
        self.assertFalse((self.root / 'evidence').exists())

    def test_attempt_retry_uses_attempt_time_even_after_recent_network_check(self):
        manifest, payload, installer = self.pending_fixture()
        installer.write_bytes(payload)
        state = {'pending': '9.0.0', 'install_attempt': '9.0.0', 'install_attempt_at': 1,
                 'last_checked': 999999}
        with patch('update_trust.verify_manifest', return_value=manifest), patch.object(update, 'game_running', return_value=False), patch.object(update.time, 'time', return_value=update.INTERVAL + 2), patch.object(update.subprocess, 'Popen') as spawn:
            update.install_pending(self.root, state)
        spawn.assert_called_once()

    def test_unsigned_release_never_becomes_pending(self):
        prefix = 'https://github.com/' + update.REPOSITORY + '/releases/download/v9.0.0/'
        release = {'draft': False, 'prerelease': False, 'tag_name': 'v9.0.0', 'assets': [
            {'name': name, 'browser_download_url': prefix + name}
            for name in ('update-manifest.json', 'update-manifest.sig')]}
        state = {}
        with patch.object(update, 'download', side_effect=[json.dumps(release).encode(), b'{}', b'bad']), patch('update_trust.verify_manifest', side_effect=ValueError('bad signature')):
            with self.assertRaises(ValueError):
                update.check_release(self.root, state)
        self.assertNotIn('pending', state)


if __name__ == '__main__':
    unittest.main()
