"""Public deployment regression tests; no real provider calls or customer data."""
import base64
import copy
import io
import json
import re
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

from core import ROOT, SKILL, AppError
from public_server import make_app

ORIGIN = 'https://agent.example.test'
SECRET = 'synthetic-test-secret-that-is-not-used-in-production'
USAGE = {'total_tokens': 20}


class Client:
    def __init__(self, app):
        self.app, self.cookie, self.csrf = app, '', ''

    def request(self, path='/', body=None, **headers):
        env = {}
        setup_testing_defaults(env)
        raw = json.dumps(body, ensure_ascii=False).encode() if body is not None else b''
        env.update(HTTP_HOST='agent.example.test', PATH_INFO=path, REQUEST_METHOD='POST' if body is not None else 'GET',
                   HTTP_COOKIE=self.cookie, HTTP_X_WORKSPACE_TOKEN=self.csrf, CONTENT_TYPE='application/json',
                   CONTENT_LENGTH=str(len(raw)), **{'wsgi.input': io.BytesIO(raw)})
        env.update(headers)
        response = {}
        def start(status, pairs):
            response.update(status=int(status.split()[0]), headers=dict(pairs))
        data = b''.join(self.app(env, start))
        if 'Set-Cookie' in response['headers']:
            self.cookie = response['headers']['Set-Cookie'].split(';')[0]
        if path == '/' and response['status'] == 200:
            self.csrf = re.search(r'name="workspace-token" content="([^"]+)"', data.decode()).group(1)
        response['data'] = json.loads(data) if response['headers']['Content-Type'].startswith('application/json') else data
        return response


class PublicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = make_app(self.temp.name, SECRET, ORIGIN)
        self.a, self.b = Client(self.app), Client(self.app)
        self.a.request(); self.b.request()

    def tearDown(self):
        self.app.runtime.process_lock.close()
        self.temp.cleanup()

    def new(self, client=None):
        r = (client or self.a).request('/api/tasks', {'title': '自拟测试任务'})
        self.assertEqual(r['status'], 201, r)
        return r['data']

    def store(self, client=None):
        client = client or self.a
        return self.app.runtime.store(self.app.runtime.verify(client.cookie.split('=', 1)[1]))

    def draft(self):
        t = self.new()
        self.a.request('/api/tasks/' + t['id'] + '/note', {'text': '请整理自拟测试材料。', 'revision': t['revision']})
        fixture = json.loads((SKILL / 'examples/brief.json').read_text())
        fixture.setdefault('rules', [])
        calls = [({'action': 'plan', 'intent': 'draft', 'fields': [], 'answers': [], 'questions': []}, USAGE),
                 ({'action': 'draft', 'brief': fixture}, USAGE)]
        with patch('agent_runtime.config_status', return_value={'ready': True}), \
             patch('agent_runtime.call_model', side_effect=calls), \
             patch('agent_runtime.compact_brief', return_value=({'action': 'draft', 'brief': {}}, USAGE)), \
             patch('agent_runtime.audit_brief', return_value=([], USAGE)), \
             patch('agent_runtime.threading.Thread'):
            result = self.a.request('/api/tasks/' + t['id'] + '/agent-run', {'revision': 1})
            self.assertEqual(result['status'], 200, result)
            store = self.store()
            store.run_agent(t['id'], result['data']['agent']['id'])
        t = self.store().view(t['id'])
        self.assertEqual(t['agent']['status'], 'ready', t['agent'].get('message'))
        return t

    def test_visitors_cannot_list_read_modify_or_download_others_tasks(self):
        t = self.new()
        uploaded = self.a.request('/api/tasks/' + t['id'] + '/upload', {'name': '自拟.md', 'data': base64.b64encode('测试需求正文'.encode()).decode()})
        self.assertEqual(uploaded['status'], 200, uploaded)
        fid = uploaded['data']['sources'][0]['id']
        self.assertNotIn('path', uploaded['data']['sources'][0])
        self.assertEqual(self.b.request('/api/tasks')['data'], [])
        for path in ['', '/data', '/files/' + fid]:
            self.assertEqual(self.b.request('/api/tasks/' + t['id'] + path)['status'], 404)
        for op, body in [('note', {'text': 'malicious'}), ('delete', {}), ('restore', {'version': 'x'}), ('version-open', {'version': 'x'}), ('agent-run', {'revision': 0})]:
            self.assertEqual(self.b.request('/api/tasks/' + t['id'] + '/' + op, body)['status'], 404)
        response = self.a.request('/api/tasks/' + t['id'] + '/files/' + fid)
        self.assertEqual(response['status'], 200)
        self.assertIn('attachment', response['headers']['Content-Disposition'])

    def test_cookie_csrf_origin_and_settings_protection(self):
        r = self.a.request()
        for flag in ['HttpOnly', 'Secure', 'SameSite=Lax']:
            self.assertIn(flag, r['headers']['Set-Cookie'])
        self.assertNotEqual(self.a.csrf, self.b.csrf)
        self.assertEqual(self.a.request('/api/tasks', {'title': 'x'}, HTTP_X_WORKSPACE_TOKEN=self.b.csrf)['status'], 403)
        self.assertEqual(self.a.request('/api/tasks', {'title': 'x'}, HTTP_ORIGIN='https://evil.test')['status'], 403)
        self.assertEqual(self.a.request('/api/tasks', HTTP_HOST='evil.test')['status'], 403)
        self.assertEqual(self.a.request('/api/tasks', HTTP_COOKIE=self.a.cookie + 'tampered')['status'], 401)
        self.assertEqual(self.a.request('/api/settings', {'api_key': 'attacker'})['status'], 403)
        self.assertEqual(self.a.request('/.env')['status'], 404)
        self.assertEqual(self.a.request('/api/cases')['data'], [])
        status = self.a.request('/api/status')['data']
        self.assertEqual(set(status['model']), {'ready'})
        self.assertNotIn('workspace_id', status)

    def test_restart_retains_session_tasks_files_and_quota(self):
        t = self.new(); runtime = self.app.runtime
        sid = runtime.verify(self.a.cookie.split('=', 1)[1])
        runtime.visitor_calls = 1; runtime.model_budget(sid)
        runtime.process_lock.close()
        self.app = make_app(self.temp.name, SECRET, ORIGIN)
        self.a.app = self.app; self.app.runtime.visitor_calls = 1
        self.assertEqual(self.a.request('/api/tasks/' + t['id'])['status'], 200)
        with self.assertRaises(AppError): self.app.runtime.model_budget(sid)

    def test_restart_marks_running_work_resumable(self):
        t = self.new(); store = self.store()
        store.add_note(t['id'], '自拟材料', 0)
        with patch('agent_runtime.config_status', return_value={'ready': True}), patch('agent_runtime.threading.Thread'):
            store.start_agent(t['id'], 1)
        self.app.runtime.process_lock.close()
        self.app = make_app(self.temp.name, SECRET, ORIGIN); self.a.app = self.app
        t = self.a.request('/api/tasks/' + t['id'])['data']
        self.assertFalse(t['busy']); self.assertEqual(t['agent']['status'], 'paused')

    def test_agent_generate_manual_edit_confirmation_and_real_exports(self):
        t = self.draft(); tid = t['id']; base = '/api/tasks/' + tid
        changed = copy.deepcopy(t['brief']); changed['scenario'] = '销售人员根据授权咨询记录整理线索，减少重复查找。'
        r = self.a.request(base + '/brief', {'brief': changed, 'revision': t['revision']})
        self.assertEqual(r['status'], 200, r)
        t = r['data']
        r = self.a.request(base + '/agent-answer', {'id': 'C-RUBRIC', 'approved': True, 'text': '同意评分', 'revision': t['revision']})
        self.assertEqual(r['status'], 200, r)
        t = r['data']
        r = self.a.request(base + '/agent-confirm', {'revision': t['revision']})
        self.assertEqual(r['status'], 200, r)
        export = r['data']['exports'][-1]
        self.assertTrue(export['agent_delivery'])
        for f in export['files']:
            path = base + '/files/' + export['id'] + '-' + f['kind']
            self.assertTrue(self.a.request(path)['data'].startswith(b'PK'))
            self.assertEqual(self.b.request(path)['status'], 404)
        vid = r['data']['versions'][0]['id']
        preview = self.a.request(base + '/version-open', {'version': vid})
        self.assertEqual(preview['status'], 200, preview)
        self.assertTrue(preview['data'].startswith(b'PK'))
        self.assertEqual(list(self.store().root.rglob('previews/**/*.docx')), [])

    def test_composer_bulk_confirmation_and_new_output_format(self):
        t = self.draft(); text = '待确认事项全部确认，输出格式为单文件html'
        plan = {'action': 'plan', 'intent': 'record', 'fields': [], 'questions': [],
                'confirm_all': {'quote': '待确认事项全部确认'}, 'answers': [
                    {'id': 'C-FORMAT', 'text': '单文件html', 'quote': '单文件html', 'selection': '', 'new_format': '单文件html'}]}
        with patch('agent_runtime.config_status', return_value={'ready': True}), patch('agent_runtime.threading.Thread'), \
             patch('agent_runtime.call_model', return_value=(plan, USAGE)):
            r = self.a.request('/api/tasks/' + t['id'] + '/agent-run', {'revision': t['revision'], 'text': text})
            self.store().run_agent(t['id'], r['data']['agent']['id'])
        t = self.a.request('/api/tasks/' + t['id'])['data']
        self.assertEqual(t['agent']['status'], 'ready', t['agent']['message'])
        self.assertTrue(t['brief']['rubric_approved'])
        self.assertTrue(t['brief']['selected_output'].startswith('F-USER-'))
        self.assertEqual(t['answers']['C-FORMAT']['text'], '单文件html')

    def test_quota_is_global_atomic_and_counts_failed_attempts(self):
        runtime = self.app.runtime; runtime.daily_calls = 3
        sids = [runtime.verify(c.cookie.split('=', 1)[1]) for c in [self.a, self.b]]
        def attempt(i):
            try: runtime.model_budget(sids[i % 2]); return True
            except AppError: return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(10))), 3)

    def test_limits_and_wrong_methods(self):
        t = self.new(); base = '/api/tasks/' + t['id']
        self.assertEqual(self.a.request(base + '/upload', {'name': 'large.md', 'data': 'A' * 5_333_337})['status'], 413)
        self.assertEqual(self.a.request(base + '/run', {'revision': 0})['status'], 404)
        self.assertEqual(self.a.request('/api/tasks', REQUEST_METHOD='DELETE')['status'], 405)
        self.app.runtime.storage_limit = 1
        self.assertEqual(self.a.request('/api/tasks', {'title': 'x'})['status'], 503)
        self.assertEqual(self.a.request(base)['status'], 200)

    def test_budget_stops_before_provider_and_keeps_progress(self):
        t = self.new(); store = self.store()
        store.add_note(t['id'], '自拟材料', 0)
        self.app.runtime.daily_calls = 1
        self.app.runtime.model_budget(store.sid)
        with patch('agent_runtime.config_status', return_value={'ready': True}), patch('agent_runtime.threading.Thread'), \
             patch('agent_runtime.call_model') as provider:
            r = self.a.request('/api/tasks/' + t['id'] + '/agent-run', {'revision': 1})
            store.run_agent(t['id'], r['data']['agent']['id'])
            provider.assert_not_called()
        t = store.get(t['id'])
        self.assertFalse(t['busy'])
        self.assertEqual(t['agent']['status'], 'paused')
        self.assertEqual(t['agent']['phase'], 'plan')
        self.assertEqual(len(t['notes']), 1)

    def test_concurrency_exhaustion_is_resumable_and_pause_works_at_storage_cap(self):
        t = self.new(); store = self.store()
        store.add_note(t['id'], '自拟材料', 0)
        with patch('agent_runtime.config_status', return_value={'ready': True}), patch('agent_runtime.threading.Thread'):
            r = self.a.request('/api/tasks/' + t['id'] + '/agent-run', {'revision': 1})
        # Reading the workspace during a run must not reinitialize AgentStore.
        self.assertIs(store, self.store())
        self.assertTrue(self.a.request('/api/tasks/' + t['id'])['data']['busy'])
        self.app.runtime.storage_limit = 1
        self.assertEqual(self.a.request('/api/tasks/' + t['id'] + '/agent-pause', {'revision': 1})['status'], 200)
        self.app.runtime.slots = threading.BoundedSemaphore(1)
        self.app.runtime.slots.acquire()
        store.run_agent(t['id'], r['data']['agent']['id'])
        self.app.runtime.slots.release()
        self.assertFalse(store.get(t['id'])['busy'])
        self.assertEqual(store.get(t['id'])['agent']['status'], 'paused')

    def test_wrong_startup_configuration_fails_closed(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaises(RuntimeError): make_app(other, 'short', ORIGIN)
            with self.assertRaises(RuntimeError): make_app(other, SECRET, 'http://public.example')
            with self.assertRaises(RuntimeError): make_app(self.temp.name, SECRET, ORIGIN)


if __name__ == '__main__':
    unittest.main()
