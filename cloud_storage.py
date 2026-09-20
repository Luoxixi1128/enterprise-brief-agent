"""Supabase REST adapter. Secrets and private object URLs never reach the browser.

All durable state is remote. The Render filesystem is only a disposable cache.
No local fallback on a cloud error: a successful save always means remote save.
"""
import hashlib
import http.client
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse

from core import AppError, clone, now, uid
from public_runtime import PublicRuntime, VisitorStore

ERRORS = {
    'private_bucket_required': '云端文件存储尚未正确初始化，请管理员检查私有存储设置。',
    'lease_lost': '网站正在切换服务，资料已保留，请稍后刷新继续。',
    'visitors_full': '公测工作区暂时已满，请稍后再来。',
    'visitors_rate': '新访客较多，请稍后再来。',
    'visitor_missing': '工作区会话已失效，请返回网站首页。',
    'global_budget': '网站今日模型调用次数已用完，进度已保存，请明日继续。',
    'visitor_budget': '此工作区今日模型调用次数已用完，进度已保存，请明日继续。',
    'storage_full': '云端文件空间已达到公测上限，已有文件仍可下载。',
    'database_full': '云端任务记录已达到公测容量上限，请先下载重要文件。',
    'tasks_full': '此工作区已达到20个任务上限。',
    'versions_full': '此任务已达到80个历史版本上限。',
    'immutable_file': '文件内容与已保存版本不一致，已保留原文件。',
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class SupabaseClient:
    def __init__(self, url=None, key=None):
        self.url = (url or os.getenv('SUPABASE_URL', '')).rstrip('/')
        self.key = key or os.getenv('SUPABASE_SECRET_KEY', '')
        parsed = urlparse(self.url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise RuntimeError('SUPABASE_URL must be the HTTPS project origin')
        if not self.key.startswith('sb_secret_') or len(self.key) < 24:
            raise RuntimeError('Set SUPABASE_SECRET_KEY to a backend sb_secret_ key, not a publishable key')
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, path, data=None, *, raw=False, method=None, extra_headers=None):
        headers = {'apikey': self.key, 'User-Agent': 'BriefAgentBackend/5.0',
                   'Content-Type': 'application/octet-stream' if raw else 'application/json'}
        headers.update(extra_headers or {})
        payload = data if raw else json.dumps(data, ensure_ascii=False).encode() if data is not None else None
        req = urllib.request.Request(self.url + path, data=payload, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=20) as response:
                content = response.read(32_000_001)
            if len(content) > 32_000_000:
                raise AppError('云端返回数据超过当前容量限制。', 503)
            return content
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            # Provider responses may contain sensitive diagnostics. Never forward
            # bodies, URLs, project IDs or credentials to visitors or logs.
            raise AppError('云端存储暂时无法连接，本次操作未确认保存，请稍后刷新重试。', 503) from None

    def rpc(self, op, sid='', owner='', body=None):
        try:
            result = json.loads(self.request('/rest/v1/rpc/brief_cloud', {'op': op, 'visitor': sid, 'owner_id': owner, 'body': body or {}}))
        except (ValueError, TypeError):
            raise AppError('云端存储返回格式异常，请稍后重试。', 503) from None
        # A task itself has error/status fields; only the RPC error envelope is
        # an HTTP failure. Business statuses such as 待上传 are never HTTP codes.
        if isinstance(result, dict) and set(result) == {'error', 'status'}:
            status = result['status'] if type(result['status']) is int and 400 <= result['status'] <= 599 else 503
            raise AppError(ERRORS.get(result['error'], '云端保存未完成，请刷新后重试。'), status)
        return result

    @staticmethod
    def object_path(key):
        return '/storage/v1/object/brief-private/' + quote(key, safe='/')

    def upload(self, key, data):
        self.request(self.object_path(key), data, raw=True, method='POST', extra_headers={'x-upsert': 'true'})

    def download(self, key):
        return self.request(self.object_path(key), raw=True, method='GET')


class SupabaseRuntime(PublicRuntime):
    def __init__(self, root, secret, origin, *, testing=False, client=None):
        # Local SQLite is used only for HTTP rate limiting, never task state.
        super().__init__(root, secret, origin, testing=testing)
        self.cloud = client or SupabaseClient()
        self.owner = secrets.token_hex(32)
        self.owned = False
        self.fenced = False
        self.last_renew = 0
        self.stop_event = threading.Event()
        self.heartbeat = None
        self.heartbeat_enabled = not testing

    def ensure_owner(self):
        with self.lock:
            if self.fenced:
                raise AppError(ERRORS['lease_lost'], 503)
            if not self.owned:
                if self.cloud.rpc('ping') != {'schema': 1}:
                    raise AppError('云端数据结构需要初始化，请管理员完成部署。', 503)
                if not self.cloud.rpc('claim', owner=self.owner).get('owned'):
                    raise AppError(ERRORS['lease_lost'], 503)
                self.owned = True
                self.last_renew = time.monotonic()
                if self.heartbeat_enabled:
                    self.heartbeat = threading.Thread(target=self._heartbeat, daemon=True)
                    self.heartbeat.start()
            elif time.monotonic() - self.last_renew > 50:
                self.renew()

    def renew(self):
        if not self.cloud.rpc('renew', owner=self.owner).get('owned'):
            self.fenced = True
            raise AppError(ERRORS['lease_lost'], 503)
        self.last_renew = time.monotonic()

    def _heartbeat(self):
        while not self.stop_event.wait(20):
            try:
                self.renew()
            except AppError:
                # Each write and model quota reservation is also fenced in SQL.
                # No heartbeat failure is treated as permission to use local data.
                if self.fenced:
                    return

    def close(self):
        self.stop_event.set()
        if self.heartbeat:
            self.heartbeat.join(timeout=22)
        # Release only when no worker is running. Otherwise use lease expiry.
        if self.owned and not any(s.active_runs for s in self.stores.values()):
            try:
                self.cloud.rpc('release', owner=self.owner)
            except AppError:
                pass
        self.process_lock.close()

    def visitor_exists(self, sid):
        return bool(self.cloud.rpc('visitor_exists', sid))

    def new_visitor(self):
        sid = secrets.token_hex(32)
        self.cloud.rpc('visitor_new', sid, body={'max_visitors': self.max_visitors})
        return sid

    def store(self, sid):
        self.ensure_owner()
        with self.lock:
            if sid not in self.stores:
                self.stores[sid] = CloudStore(self.root / 'visitors' / sid, self, sid)
            return self.stores[sid]

    def storage_guard(self, store, extra=0):
        self.cloud.rpc('storage_guard', store.sid, self.owner, {'extra': extra})

    def model_budget(self, sid):
        self.ensure_owner()
        self.cloud.rpc('model_budget', sid, self.owner,
                       {'global_limit': self.daily_calls, 'visitor_limit': self.visitor_calls})


class CloudStore(VisitorStore):
    def __init__(self, root, runtime, sid):
        self.runtime, self.sid = runtime, sid
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.export_lock = threading.Lock()
        self.download_lock = threading.Lock()
        self.active_runs = set()
        self.recover_pending = set()
        # Only the instance holding the database lease may recover a checkpoint.
        # It cannot mark another live deployment's running task interrupted.
        for t in self.list_full():
            if t.get('busy') or t.get('agent', {}).get('status') == 'running':
                t.update(busy=False, status='已暂停', error='')
                if t.get('agent'):
                    t['agent'].update(status='paused', pause_requested=False,
                                      message='服务已重新启动，已保存的步骤可继续处理。')
                self.save(t)

    def connect(self):
        raise RuntimeError('CloudStore cannot use a local task database')

    def rpc(self, op, body=None):
        return self.runtime.cloud.rpc(op, self.sid, self.runtime.owner, body)

    def _cache_path(self, relative):
        p = PurePosixPath(relative)
        if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] not in ('files', 'exports'):
            raise AppError('文件位置无效。', 404)
        dest = (self.root / relative).resolve()
        if not dest.is_relative_to(self.root):
            raise AppError('文件位置无效。', 404)
        return dest

    @staticmethod
    def _files(task):
        return list(task.get('sources', [])) + [f for e in task.get('exports', []) for f in e['files']]

    def _paths(self, task, decode=False):
        files = self._files(task) + task.get('agent', {}).get('original', {}).get('sources', [])
        for f in files:
            if 'path' not in f:
                continue
            if decode:
                f['path'] = str(self._cache_path(f['path']))
            else:
                path = Path(f['path']).resolve()
                if not path.is_relative_to(self.root):
                    raise AppError('文件位置无效。', 404)
                f['path'] = path.relative_to(self.root).as_posix()
        return task

    def save(self, task):
        task['updated_at'] = now()
        remote = clone(task)
        pending = remote.pop('_pending_versions', [])
        for f in self._files(remote):
            if f.get('cloud_saved'):
                continue
            path = Path(f['path']).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                raise AppError('待保存文件不可用。', 503)
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            key = self.sid + '/' + path.relative_to(self.root).as_posix()
            reserved = self.rpc('reserve_file', {'key': key, 'bytes': len(data), 'sha256': digest})
            if not reserved.get('ready'):
                self.runtime.cloud.upload(key, data)
                self.rpc('file_ready', {'key': key})
            f.update(cloud_saved=True, sha256=digest)
        # A single DB transaction persists both the new task and its snapshots.
        self.rpc('save', {'task': self._paths(remote), 'versions': pending})
        task.pop('_pending_versions', None)

    def get(self, tid, include_deleted=False):
        task = self.rpc('get', {'id': tid})
        if not task:
            raise AppError('任务不存在。', 404)
        if task.get('deleted_at') and not include_deleted:
            raise AppError('任务已删除，可在“已删除任务”中恢复。', 404)
        task = self._paths(task, decode=True)
        with self.lock:
            if tid in self.recover_pending:
                if task.get('busy'):
                    task.update(busy=False, status='已暂停', error='')
                    task['agent'].update(status='paused', pause_requested=False,
                                         message='云端连接曾中断，请从已保存的步骤继续。')
                    self.save(task)
                self.recover_pending.discard(tid)
        return task

    def list_full(self):
        for tid in list(self.recover_pending):
            self.get(tid, include_deleted=True)
        return [self._paths(t, decode=True) for t in self.rpc('list')]

    def run_agent(self, tid, run_id):
        with self.lock:
            self.active_runs.add(tid)
        try:
            super().run_agent(tid, run_id)
        except AppError:
            # Even the interruption checkpoint may fail during an outage.
            # Recover from the last remote checkpoint when connectivity returns.
            with self.lock:
                self.recover_pending.add(tid)
        finally:
            with self.lock:
                self.active_runs.discard(tid)

    def snapshot(self, task, label):
        if len(self.versions(task['id'])) >= 80:
            raise AppError('此任务已达到80个历史版本上限。', 429)
        version = {'id': uid(), 'task_id': task['id'], 'created_at': now(), 'label': label,
                   'revision': task['revision'], 'brief': clone(task['brief']),
                   'answers': clone(task['answers']), 'scope_authorization': task['scope_authorization']}
        task.setdefault('_pending_versions', []).append(version)
        return version

    def versions(self, tid):
        self.get(tid)
        versions = sorted(self.rpc('versions', {'id': tid}), key=lambda v: v['created_at'])
        for i, v in enumerate(versions, 1):
            v['number'] = i
        return list(reversed(versions))

    def file(self, tid, fid):
        task = self.get(tid)
        f = next((s for s in task['sources'] if s['id'] == fid), None)
        if not f:
            f = next((item for e in task['exports'] for item in e['files'] if fid == e['id'] + '-' + item['kind']), None)
        if not f:
            raise AppError('文件不存在。', 404)
        path = self._cache_path(Path(f['path']).relative_to(self.root).as_posix())
        with self.download_lock:
            if not path.is_file():
                data = self.runtime.cloud.download(self.sid + '/' + path.relative_to(self.root).as_posix())
                if hashlib.sha256(data).hexdigest() != f['sha256']:
                    raise AppError('云端文件校验未通过，请稍后重试。', 503)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        return path, f['name']
