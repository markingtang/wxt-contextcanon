"""Regressions for real installation, recovery and protocol failures."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'packages'), str(ROOT / 'deploy/release-guard')]
from profile_core import ProfileService, ProfileStore
from registry_core import RegistryService, RegistryStore
from contextcanon_cli.demo import seed
from mcp_server.server import build_server
import guard


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='contextcanon-hardening-')
        self.home = Path(self.tmp.name)
        self.p = ProfileService(ProfileStore(str(self.home / 'profile.db')))
        self.r = RegistryService(RegistryStore(str(self.home / 'registry.db')))

    def tearDown(self):
        self.p.store.close()
        self.r.store.close()
        self.tmp.cleanup()

    def cli(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith('WXT_CONTEXTCANON_')}
        env.update(PYTHONPATH=str(ROOT / 'packages'), PYTHONIOENCODING='utf-8')
        return subprocess.run([sys.executable, '-m', 'contextcanon_cli', *args],
                              cwd=self.home, env=env, capture_output=True, text=True,
                              encoding='utf-8', timeout=30)

    def test_guard_cli_failure_exit(self):
        config = self.home / 'deploy.json'
        config.write_text(json.dumps({'project_name': 'test', 'backup_command': 'exit 7'}))
        result = self.cli('guard', 'apply', '--deploy-config', str(config), '--intent', 'test')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['outcome'], 'aborted')
        self.assertFalse((self.home / 'data/deploy.lock').exists())

    def test_guard_backup_timeout_priority_and_no_deploy(self):
        class FailedBackup:
            name = 'fake'
            def run(self, *args, **kwargs):
                return {'ok': False, 'stderr': '', 'error': 'timeout'}
        config = dict(guard.DEPLOY_DEFAULTS, backup_command='synthetic')
        result = guard.ReleaseGuard(config, str(self.home), FailedBackup()).run(True, 'test', False)
        self.assertIn('timeout', result['error'])
        failure = next(s for s in result['steps'] if s['step'] == 'fail_closed')
        self.assertEqual(failure['failed_step'], 'backup_gate')
        self.assertNotIn('deploy', [s['step'] for s in result['steps']])
        self.assertFalse((self.home / 'data/deploy.lock').exists())

    def test_guard_plan_writes_no_baseline_or_lock(self):
        (self.home / 'input.yml').write_text('services: {}')
        config = dict(guard.DEPLOY_DEFAULTS, compose_files=['input.yml'], integrity_file='baseline.json')
        result = guard.ReleaseGuard(config, str(self.home)).run(False, None, False)
        self.assertEqual(result['outcome'], 'planned')
        self.assertEqual([p.name for p in self.home.iterdir() if p.suffix not in ('.db', '.yml')], [])

    def test_guard_interrupt_releases_owned_lock(self):
        obj = guard.ReleaseGuard(dict(guard.DEPLOY_DEFAULTS), str(self.home))
        with patch.object(obj, 'deploy', side_effect=KeyboardInterrupt):
            result = obj.run(True, 'test', True)
        self.assertEqual(result['outcome'], 'aborted')
        self.assertEqual(result['error'], 'interrupted')
        self.assertFalse(Path(obj.lock_path).exists())

    def test_guard_does_not_remove_existing_stale_lock(self):
        lock = self.home / 'existing.lock'
        lock.write_text('owned elsewhere')
        os.utime(lock, (1, 1))
        result = guard.ReleaseGuard(dict(guard.DEPLOY_DEFAULTS, lock_path=str(lock)), str(self.home)).run(True, 'test', True)
        self.assertEqual(result['outcome'], 'aborted')
        self.assertEqual(lock.read_text(), 'owned elsewhere')

    def test_guard_apply_requires_backup_or_explicit_skip(self):
        result = guard.ReleaseGuard(dict(guard.DEPLOY_DEFAULTS), str(self.home)).run(True, 'test', False)
        self.assertEqual(result['outcome'], 'aborted')

    def test_failed_rebuild_preserves_index_and_applied_markers(self):
        event = self.r.append_event('file.upsert', {'object_key': 'a'})
        self.r.apply_all()
        before = self.r.query()
        self.r.store.append_event('bad', 'd', 'file.upsert', '2026-01-01T00:00:00Z', {})
        result = self.r.offline_recovery()
        self.assertFalse(result['converged'])
        self.assertEqual(self.r.query(), before)
        self.assertTrue(self.r.store.already_applied(event['event_id']))
        self.assertFalse(self.r.store.already_applied('bad'))

    def test_corrupt_event_json_rolls_back_rebuild(self):
        self.r.append_event('file.upsert', {'object_key': 'a'})
        self.r.apply_all()
        before = self.r.query()
        self.r.store.conn.execute("UPDATE events SET payload = '{bad'")
        self.r.store.commit()
        self.assertTrue(self.r.rebuild_shared_index()['last_good_used'])
        self.assertEqual(self.r.query(), before)

    def test_invalid_outbox_is_not_inserted_into_ledger(self):
        self.r.store.enqueue('bad', 'd', 'file.move', {'object_key': 'a'}, '2026-01-01T00:00:00Z')
        self.assertEqual(self.r.drain_outbox()['failed'], 1)
        self.assertFalse(self.r.store.has_event('bad'))
        self.assertFalse(self.r.offline_recovery()['converged'])

    def test_event_identity_conflict_rejected(self):
        self.r.append_event('file.upsert', {'object_key': 'a'}, event_id='id')
        with self.assertRaises(ValueError):
            self.r.append_event('file.delete', {'object_key': 'a'}, event_id='id')

    def test_outbox_projection_matches_rebuild(self):
        self.r.store.enqueue('a', 'd', 'file.upsert', {'object_key': 'a'}, '2020-01-01T00:00:00Z')
        self.r.drain_outbox()
        before = self.r.query()[0]['state']
        self.r.rebuild_shared_index()
        self.assertEqual(self.r.query()[0]['state'], before)

    def test_registry_failure_cli_is_nonzero(self):
        db = self.home / 'data/registry/shared.db'
        with RegistryStore(str(db)) as store:
            store.append_event('bad', 'd', 'file.move', '2020-01-01T00:00:00Z', {})
        self.assertNotEqual(self.cli('registry', 'rebuild').returncode, 0)
        self.assertNotEqual(self.cli('registry', 'recover').returncode, 0)

    def test_profile_timezone_window_and_invalid_dates(self):
        self.p.upsert_fact('s', 'k', 'v', valid_from='2020-01-01T08:00:00+08:00', valid_until='2020-01-02T00:00:00Z')
        self.assertEqual(len(self.p.as_of('s', '2020-01-01T00:00:00Z')), 1)
        self.assertEqual(self.p.as_of('s', '2020-01-02T00:00:00Z'), [])
        for value in ('not-a-date', '2020-01-01', '2020-01-01T00:00:00'):
            with self.assertRaises(ValueError):
                self.p.as_of('s', value)

    def test_profile_metadata_change_creates_revision(self):
        self.p.upsert_fact('s', 'k', 'v', sensitivity='public')
        self.p.upsert_fact('s', 'k', 'v', sensitivity='restricted')
        self.assertEqual(self.p.get_fact('s', 'k')['sensitivity'], 'restricted')
        self.assertEqual(len(self.p.history('s', 'k')), 2)

    def test_reassertion_keeps_provenance_in_audit(self):
        self.p.upsert_fact('s', 'k', 'v', provenance={'source': 'first'})
        self.p.upsert_fact('s', 'k', 'v', provenance={'source': 'second'})
        payload = self.p.audit('s')[0]['payload']
        self.assertEqual(payload['previous_provenance']['source'], 'first')
        self.assertEqual({s['source_id'] for s in self.p.store.list_sources()}, {'first', 'second'})

    def test_profile_failed_write_is_atomic(self):
        with patch.object(self.p.store, 'append_event', side_effect=RuntimeError('fail')):
            with self.assertRaises(RuntimeError):
                self.p.upsert_fact('s', 'k', 'v')
        self.assertEqual(self.p.history('s', 'k'), [])
        self.p.upsert_fact('s', 'k', 'after')
        self.assertEqual(self.p.get_fact('s', 'k')['revision'], 1)

    def test_simultaneous_profile_writers_have_distinct_revisions(self):
        def write(i):
            with ProfileStore(str(self.home / 'profile.db')) as store:
                ProfileService(store).upsert_fact('s', 'concurrent', i)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(12)))
        self.assertEqual([f['revision'] for f in self.p.history('s', 'concurrent')], list(range(1, 13)))

    def test_current_lookup_does_not_decode_unrelated_facts(self):
        for i in range(20):
            self.p.upsert_fact('s', 'key%d' % i, i)
        with patch.object(self.p.store, '_decode', wraps=self.p.store._decode) as decode:
            self.assertEqual(self.p.get_fact('s', 'key5')['value'], 5)
            self.assertEqual(decode.call_count, 1)

    def test_nested_boolean_number_change_not_unchanged(self):
        self.p.upsert_fact('s', 'k', {'a': [True]})
        self.assertEqual(self.p.upsert_fact('s', 'k', {'a': [1]})['action'], 'superseded')

    def test_demo_can_be_seeded_twice_without_reset(self):
        persona = str(ROOT / 'examples/demo-persona/alex-chen.facts.json')
        seed(self.p, persona)
        seed(self.p, persona)
        self.assertEqual(self.p.get_fact('demo:alex-chen', 'tooling.editor')['value'], 'zed')

    def test_relative_history_cli(self):
        self.assertEqual(self.cli('demo', 'seed', '--reset').returncode, 0)
        result = self.cli('profile', 'as-of', '--days-ago', '30')
        self.assertEqual(result.returncode, 0, result.stderr)
        facts = {f['key']: f['value'] for f in json.loads(result.stdout)['facts']}
        self.assertEqual(facts['tooling.editor'], 'vscode')

    def test_mcp_schema_json_values_notifications_and_bad_call(self):
        server = build_server(root=str(self.home))
        try:
            spec = next(t for t in server.tool_specs() if t['name'] == 'profile_upsert')
            self.assertNotIn('type', spec['inputSchema']['properties']['value'])
            self.assertIsNone(server.handle({'jsonrpc': '2.0', 'method': 'tools/call', 'params': {'name': 'profile_upsert'}}))
            result = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': [], 'arguments': {}}})
            self.assertEqual(result['error']['code'], -32602)
            self.assertIn('result', server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}))
            discover = server.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'server/discover'})
            self.assertEqual(discover['error']['code'], -32601)  # dual-era clients fall back
        finally:
            server.close()

    def test_mcp_internal_error_does_not_echo_sensitive_value(self):
        server = build_server(root=str(self.home))
        try:
            with patch.object(server.profile, 'get_fact', side_effect=RuntimeError('private sentinel value')):
                result = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'profile_get', 'arguments': {'subject': 's', 'key': 'k'}}})
            self.assertNotIn('private sentinel value', json.dumps(result))
        finally:
            server.close()

    def test_fake_service_owned_start_smoke_stop(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, CONTEXTCANON_FAKE_PORT=str(port), CONTEXTCANON_FAKE_STATE=str(self.home / 'fake.json'))
        script = str(ROOT / 'deploy/release-guard/fake_stack/fake_service.py')
        def run(action):
            return subprocess.run([sys.executable, script, action], env=env, cwd=self.home,
                                  capture_output=True, timeout=15).returncode
        try:
            fixture = str(ROOT / 'deploy/release-guard/fake_stack/fake_deploy.json')
            config = guard.load_deploy_config(fixture)
            config.update(health_endpoints=['http://127.0.0.1:%d/health' % port],
                          deploy_command='%s %s --start' % (guard.LocalShell.quote(sys.executable), guard.LocalShell.quote(script)),
                          smoke_command='%s %s --smoke' % (guard.LocalShell.quote(sys.executable), guard.LocalShell.quote(script)),
                          backup_command='%s %s' % (guard.LocalShell.quote(sys.executable), guard.LocalShell.quote(str(ROOT / 'deploy/release-guard/fake_stack/fake_backup.py'))),
                          migration_test_command='%s %s' % (guard.LocalShell.quote(sys.executable), guard.LocalShell.quote(str(ROOT / 'deploy/release-guard/fake_stack/fake_migration_test.py'))),
                          workdir=str(self.home))
            with patch.dict(os.environ, env):
                result = guard.ReleaseGuard(config, str(self.home)).run(True, 'synthetic lifecycle', False)
            self.assertEqual(result['outcome'], 'applied', result)
            self.assertTrue((self.home / 'data/backup.marker').is_file())
            self.assertEqual(run('--smoke'), 0)
            self.assertEqual(run('--start'), 0)
        finally:
            self.assertEqual(run('--stop'), 0)
        self.assertNotEqual(run('--smoke'), 0)
        self.assertFalse((self.home / 'fake.json').exists())
