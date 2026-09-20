"""PostgreSQL-backed integration tests with a local REST/object-storage stand-in.

Install the pinned QA dependency with npm ci --prefix tests_cloud. These tests
do not connect to Supabase, Render, or a model provider.
"""
import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

import test_public
from agent_runtime import basis
from cloud_storage import SupabaseClient
from core import AppError, uid
from public_server import make_app


class CloudTests(test_public.PublicTests):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).parent
        if not (root / 'tests_cloud/node_modules/@electric-sql/pglite').exists():
            raise unittest.SkipTest('Run npm ci --prefix tests_cloud first')
        cls.key = 'sb_secret_synthetic_local_test_only'
        cls.log = tempfile.TemporaryFile(mode='w+t')
        cls.server = subprocess.Popen([os.getenv('NODE_BINARY', 'node'), str(root / 'tests_cloud/server.mjs')],
                                      stdout=subprocess.PIPE, stderr=cls.log, text=True,
                                      env={**os.environ, 'QA_KEY': cls.key})
        line = cls.server.stdout.readline()
        if not line:
            cls.log.seek(0)
            raise RuntimeError(cls.log.read())
        cls.url = 'http://127.0.0.1:' + str(json.loads(line)['port'])

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.server.stdout.close()
        cls.log.seek(0)
        errors = cls.log.read()
        cls.log.close()
        if errors:
            raise AssertionError('SQL/REST errors during cloud tests:\n' + errors)

    def setUp(self):
        self.cloud = SupabaseClient('https://synthetic.example.test', self.key)
        # The only HTTP override lives in the test harness, never production.
        self.cloud.url = self.url
        self.admin('reset')
        self.temp = tempfile.TemporaryDirectory()
        self.app = make_app(self.temp.name, test_public.SECRET, test_public.ORIGIN, testing=True, cloud_client=self.cloud)
        self.a, self.b = test_public.Client(self.app), test_public.Client(self.app)
        self.assertEqual(self.a.request()['status'], 200)
        self.assertEqual(self.b.request()['status'], 200)

    def tearDown(self):
        self.admin('fail', target=None)
        self.app.runtime.close()
        self.temp.cleanup()

    def admin(self, op, **body):
        return json.loads(self.cloud.request('/__qa', {'op': op, **body}))

    def reboot_without_cache(self):
        self.app.runtime.close()
        self.temp.cleanup()
        self.temp = tempfile.TemporaryDirectory()
        self.app = make_app(self.temp.name, test_public.SECRET, test_public.ORIGIN, testing=True, cloud_client=self.cloud)
        self.a.app = self.b.app = self.app

    def test_restart_retains_session_tasks_files_and_quota(self):
        t = self.draft(); base = '/api/tasks/' + t['id']
        raw = '这是重启恢复用的自拟需求材料。'.encode()
        r = self.a.request(base + '/upload', {'name': 'test.md', 'data': base64.b64encode(raw).decode()})
        self.assertEqual(r['status'], 200, r)
        t = r['data']
        # Apply the added material through the supported manual-edit route.
        r = self.a.request(base + '/brief', {'brief': t['brief'], 'revision': t['revision']})
        self.assertEqual(r['status'], 200, r)
        t = r['data']
        r = self.a.request(base + '/agent-answer', {'id': 'C-RUBRIC', 'approved': True, 'text': '同意评分', 'revision': t['revision']})
        t = r['data']
        delivered = self.a.request(base + '/agent-confirm', {'revision': t['revision']})
        self.assertEqual(delivered['status'], 200, delivered)
        saved = self.store().get(t['id'])
        export = delivered['data']['exports'][-1]
        before_basis = basis(saved)
        urls = [base + '/files/' + saved['sources'][0]['id']] + [base + '/files/' + export['id'] + '-' + f['kind'] for f in export['files']]
        original_files = [self.a.request(url)['data'] for url in urls]
        self.app.runtime.visitor_calls = 24
        self.app.runtime.model_budget(self.store().sid)
        self.reboot_without_cache()
        r = self.a.request(base)
        self.assertEqual(r['status'], 200, r)
        self.assertEqual(r['data']['answers'], delivered['data']['answers'])
        self.assertEqual(r['data']['versions'], delivered['data']['versions'])
        self.assertEqual(basis(self.store().get(t['id'])), before_basis)
        self.assertEqual([self.a.request(url)['data'] for url in urls], original_files)
        for url in urls:
            self.assertEqual(self.b.request(url)['status'], 404)
        self.app.runtime.visitor_calls = 1
        with self.assertRaises(AppError): self.app.runtime.model_budget(self.store().sid)
        preview = self.a.request(base + '/version-open', {'version': r['data']['versions'][0]['id']})
        self.assertEqual(preview['status'], 200, preview)
        self.assertTrue(preview['data'].startswith(b'PK'))

    def test_restart_marks_running_work_resumable(self):
        t = self.new(); store = self.store()
        store.add_file(t['id'], 'a.md', base64.b64encode('自拟需求文本'.encode()).decode())
        with patch('agent_runtime.config_status', return_value={'ready': True}), patch('agent_runtime.threading.Thread'):
            r = store.start_agent(t['id'], 1)
        saved_basis = basis(store.get(t['id']))
        self.reboot_without_cache()
        t = self.a.request('/api/tasks/' + t['id'])['data']
        self.assertFalse(t['busy']); self.assertEqual(t['agent']['status'], 'paused')
        self.assertEqual(basis(self.store().get(t['id'])), saved_basis)
        with patch('agent_runtime.config_status', return_value={'ready': True}), patch('agent_runtime.threading.Thread'):
            resumed = self.store().start_agent(t['id'], t['revision'], resume=True)
        self.assertEqual(resumed['agent']['id'], r['agent']['id'])

    def test_limits_and_wrong_methods(self):
        t = self.new(); base = '/api/tasks/' + t['id']
        self.assertEqual(self.a.request(base + '/upload', {'name': 'large.md', 'data': 'A' * 5_333_337})['status'], 413)
        self.assertEqual(self.a.request(base + '/run', {'revision': 0})['status'], 404)
        self.assertEqual(self.a.request('/api/tasks', REQUEST_METHOD='DELETE')['status'], 405)
        sid = self.store().sid
        self.admin('sql', sql='insert into public.brief_files values($1,$2,50000001,$3,true)', params=[sid, sid + '/files/reserved', 'test'])
        self.assertEqual(self.a.request('/api/tasks', {'title': 'x'})['status'], 413)
        self.assertEqual(self.a.request(base)['status'], 200)

    def test_cloud_failures_do_not_report_success_or_use_local_fallback(self):
        t = self.new(); base = '/api/tasks/' + t['id']
        self.admin('fail', target='save')
        r = self.a.request(base + '/note', {'text': '这个更新未保存', 'revision': 0})
        self.assertEqual(r['status'], 503)
        self.assertNotIn('private_detail', json.dumps(r))
        self.admin('fail', target=None)
        self.assertEqual(self.a.request(base)['data']['notes'], [])
        self.admin('fail', target='upload')
        r = self.a.request(base + '/upload', {'name': 'test.md', 'data': base64.b64encode(b'synthetic text').decode()})
        self.assertEqual(r['status'], 503)
        self.admin('fail', target=None)
        self.assertEqual(self.a.request(base)['data']['sources'], [])
        self.assertFalse(list((Path(self.temp.name) / 'visitors').rglob('*.sqlite*')))

    def test_interrupted_checkpoint_recovers_after_connection_returns(self):
        t = self.new(); store = self.store()
        store.add_note(t['id'], '自拟材料', 0)
        with patch('agent_runtime.config_status', return_value={'ready': True}), patch('agent_runtime.threading.Thread'):
            r = store.start_agent(t['id'], 1)
        self.admin('fail', target='all')
        store.run_agent(t['id'], r['agent']['id'])
        self.admin('fail', target=None)
        recovered = self.a.request('/api/tasks/' + t['id'])['data']
        self.assertFalse(recovered['busy'])
        self.assertEqual(recovered['agent']['status'], 'paused')
        self.assertEqual(recovered['agent']['id'], r['agent']['id'])
        self.assertEqual(len(recovered['notes']), 1)

    def test_deployment_lease_blocks_second_writer_and_fences_old_owner(self):
        t = self.new(); old = self.store(); sid = old.sid
        with tempfile.TemporaryDirectory() as root:
            other = make_app(root, test_public.SECRET, test_public.ORIGIN, testing=True, cloud_client=self.cloud)
            try:
                with self.assertRaises(AppError): other.runtime.store(sid)
                self.admin('expire')
                new = other.runtime.store(sid)
                self.assertEqual(new.get(t['id'])['id'], t['id'])
                with self.assertRaises(AppError): old.save(old.get(t['id']))
                with self.assertRaises(AppError): self.app.runtime.model_budget(sid)
                with self.assertRaises(AppError): self.app.runtime.renew()
                self.assertTrue(self.app.runtime.fenced)
            finally:
                other.runtime.close()

    def test_file_reservations_and_database_limits(self):
        self.new(); store = self.store()
        key = store.sid + '/files/test.txt'
        self.assertFalse(store.rpc('reserve_file', {'key': key, 'bytes': 10, 'sha256': 'a'})['ready'])
        store.rpc('file_ready', {'key': key})
        self.assertTrue(store.rpc('reserve_file', {'key': key, 'bytes': 10, 'sha256': 'a'})['ready'])
        with self.assertRaises(AppError): store.rpc('reserve_file', {'key': key, 'bytes': 10, 'sha256': 'b'})
        with self.assertRaises(AppError): store.rpc('reserve_file', {'key': 'b'*64+'/files/test', 'bytes': 10, 'sha256': 'a'})
        with self.assertRaises(AppError): store.rpc('save', {'task': {'id': uid(), 'text': 'a'*6000001}})
        self.assertEqual(len(store.list_full()),1)

    def test_anonymous_visitor_limit_is_durable(self):
        self.app.runtime.max_visitors = 2
        c = test_public.Client(self.app)
        self.assertEqual(c.request()['status'], 503)
        self.reboot_without_cache()
        self.app.runtime.max_visitors = 2
        self.assertEqual(test_public.Client(self.app).request()['status'], 503)
        self.assertEqual(self.a.request()['status'], 200)

    def test_corrupted_remote_file_is_not_delivered(self):
        t = self.new(); store = self.store()
        r = store.add_file(t['id'], 'a.md', base64.b64encode(b'synthetic material').decode())
        source = store.get(t['id'])['sources'][0]
        key = store.sid + '/' + Path(source['path']).relative_to(store.root).as_posix()
        self.reboot_without_cache()
        self.admin('corrupt', key=key)
        result = self.a.request('/api/tasks/' + t['id'] + '/files/' + r['sources'][0]['id'])
        self.assertEqual(result['status'],503)
        self.assertIn('校验未通过',result['data']['error'])

    def test_version_commit_retry_is_idempotent_at_limit(self):
        t = self.new(); store = self.store()
        versions = [{'id':uid(),'task_id':t['id'],'created_at':str(i)} for i in range(80)]
        task = store.get(t['id'])
        store.rpc('save', {'task':task,'versions':versions})
        store.rpc('save', {'task':task,'versions':versions})
        self.assertEqual(len(store.rpc('versions', {'id':t['id']})),80)
        with self.assertRaises(AppError):
            store.rpc('save', {'task':task,'versions':[{'id':uid(),'task_id':t['id']}]})


if __name__ == '__main__':
    unittest.main()
