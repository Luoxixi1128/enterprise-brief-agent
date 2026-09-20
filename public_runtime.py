"""Persistent visitor isolation and bounded public-beta resource use.

Run in ONE process: AgentStore uses threads and per-workspace locks. The process
lock prevents accidentally starting independent workers against live tasks.
"""
import fcntl
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from agent_runtime import AgentStore, AgentPause
from core import AppError


class PublicRuntime:
    def __init__(self, root, secret, origin, *, testing=False):
        if len(secret) < 32:
            raise RuntimeError('PUBLIC_SESSION_SECRET must contain at least 32 characters')
        if not re.fullmatch(r'https://[a-zA-Z0-9.-]+(?::\d+)?', origin):
            if not testing or not re.fullmatch(r'http://(?:127\.0\.0\.1|localhost):\d+', origin):
                raise RuntimeError('PUBLIC_ORIGIN must be an HTTPS origin without a path')
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.process_lock = (self.root / '.process.lock').open('a')
        try:
            fcntl.flock(self.process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.process_lock.close()
            raise RuntimeError('Use exactly one worker per public data directory') from None
        self.secret, self.origin = secret.encode(), origin
        self.secure = origin.startswith('https:')
        self.db = self.root / 'public.sqlite3'
        self.lock = threading.RLock()
        self.stores = {}
        self.slots = threading.BoundedSemaphore(int(os.getenv('PUBLIC_CONCURRENT_RUNS', '2')))
        self.visitor_calls = int(os.getenv('PUBLIC_VISITOR_DAILY_CALLS', '240'))
        self.daily_calls = int(os.getenv('PUBLIC_DAILY_CALLS', '300'))
        self.max_visitors = int(os.getenv('PUBLIC_MAX_VISITORS', '200'))
        self.storage_limit = int(os.getenv('PUBLIC_STORAGE_MB', '700')) * 1_000_000
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS visitors(id TEXT PRIMARY KEY, created INTEGER);'
                             'CREATE TABLE IF NOT EXISTS counters(scope TEXT, bucket TEXT, n INTEGER, '
                             'PRIMARY KEY(scope,bucket));')

    def connect(self):
        return sqlite3.connect(self.db, timeout=15)

    def signature(self, text):
        return hmac.new(self.secret, text.encode(), hashlib.sha256).hexdigest()

    def csrf(self, sid):
        return self.signature('csrf:' + sid)

    def cookie(self, sid):
        content = sid + '.' + str(int(time.time()) + 90 * 86400)
        return content + '.' + self.signature('cookie:' + content)

    def verify(self, value):
        match = re.fullmatch(r'([a-f0-9]{64})\.(\d{10})\.([a-f0-9]{64})', value or '')
        if not match:
            return None
        sid, expires, signature = match.groups()
        if not secrets.compare_digest(signature, self.signature('cookie:' + sid + '.' + expires)):
            return None
        if not time.time() < int(expires) <= time.time() + 90 * 86400 + 60:
            return None
        return sid if self.visitor_exists(sid) else None

    def visitor_exists(self, sid):
        with self.connect() as db:
            return bool(db.execute('SELECT 1 FROM visitors WHERE id=?', (sid,)).fetchone())

    def consume(self, quotas):
        """Reserve all budgets atomically; failed provider calls also cost a slot."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for scope, bucket, limit, message in quotas:
                row = db.execute('SELECT n FROM counters WHERE scope=? AND bucket=?', (scope, bucket)).fetchone()
                if row and row[0] >= limit:
                    raise AppError(message, 429)
            for scope, bucket, _, _ in quotas:
                db.execute('INSERT INTO counters VALUES (?,?,1) ON CONFLICT(scope,bucket) DO UPDATE SET n=n+1', (scope, bucket))
            db.execute('DELETE FROM counters WHERE bucket < ?', (time.strftime('%Y-%m-%d', time.gmtime(time.time() - 3 * 86400)),))

    def rate(self, sid=None, mutation=False):
        minute = time.strftime('%Y-%m-%dT%H:%M', time.gmtime())
        quotas = [('http:global', minute, 1200, '访问较多，请稍后再试。')]
        if sid:
            quotas.append(('http:' + sid, minute, 180, '操作过于频繁，请稍后再试。'))
            if mutation:
                quotas.append(('write:' + sid, minute, 30, '保存过于频繁，请稍后再试。'))
        self.consume(quotas)

    def new_visitor(self):
        with self.lock, self.connect() as db:
            if db.execute('SELECT COUNT(*) FROM visitors').fetchone()[0] >= self.max_visitors:
                raise AppError('公测工作区暂时已满，请稍后再来。', 503)
            self.consume([('visitors', time.strftime('%Y-%m-%dT%H', time.gmtime()), 30, '新访客较多，请稍后再来。')])
            sid = secrets.token_hex(32)
            db.execute('INSERT INTO visitors VALUES (?,?)', (sid, int(time.time())))
            return sid

    def store(self, sid):
        # sid is derived from a verified cookie or created internally, never a URL.
        with self.lock:
            if sid not in self.stores:
                self.stores[sid] = VisitorStore(self.root / 'visitors' / sid, self, sid)
            return self.stores[sid]

    @staticmethod
    def size(path):
        return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())

    def storage_guard(self, store, extra=0):
        if self.size(store.root) + extra > 50_000_000:
            raise AppError('此浏览器工作区已达到公测存储上限，请先下载已有文件。', 413)
        if self.size(self.root) + extra > self.storage_limit:
            raise AppError('网站存储空间暂时不足，已保存的文件仍可下载。', 503)

    def model_budget(self, sid):
        day = time.strftime('%Y-%m-%d', time.gmtime())
        self.consume([('model:global', day, self.daily_calls, '网站今日模型调用次数已用完，进度已保存，请明日继续。'),
                      ('model:' + sid, day, self.visitor_calls, '此工作区今日模型调用次数已用完，进度已保存，请明日继续。')])


class VisitorStore(AgentStore):
    def __init__(self, root, runtime, sid):
        self.runtime, self.sid = runtime, sid
        super().__init__(root)

    def new(self, title, company=''):
        with self.lock:
            if len(self.list_full()) >= 20 and not self.find_existing(title, company):
                raise AppError('每个浏览器工作区最多创建20个任务（含已删除任务）。', 429)
            return super().new(title, company)

    def start(self, *args, **kwargs):
        raise AppError('请使用提交需求页面的 Agent 入口。', 403)

    def start_agent(self, tid, revision, text='', resume=False, reply_to=None):
        with self.lock:
            if any(t.get('busy') for t in self.list_full()):
                raise AppError('此工作区已有任务在处理，请等待完成或暂停后再提交。', 409)
            return super().start_agent(tid, revision, text, resume, reply_to)

    def run_agent(self, tid, run_id):
        if not self.runtime.slots.acquire(blocking=False):
            with self.lock:
                t = self.get(tid)
                t['agent'].update(status='paused', message='网站正在处理其他任务，进度已保存，请稍后点击继续。')
                t.update(busy=False, status='已暂停')
                self.save(t)
            return
        try:
            super().run_agent(tid, run_id)
        finally:
            self.runtime.slots.release()

    def _call(self, tid, agent, label, fn):
        def bounded():
            try:
                self.runtime.model_budget(self.sid)
            except AppError as e:
                raise AgentPause(str(e)) from None
            return fn()
        return super()._call(tid, agent, label, bounded)

    def add_file(self, tid, name, encoded):
        with self.lock:
            if len(encoded) > 5_333_336:
                raise AppError('公开版单文件上限为4MB，请拆分材料。', 413)
            if len(self.get(tid)['sources']) >= 8:
                raise AppError('公开版每个任务最多8份材料。', 413)
            return super().add_file(tid, name, encoded)

    def add_note(self, tid, text, revision=None, scope=False, user_instruction=False):
        with self.lock:
            if len(self.get(tid)['notes']) >= 40:
                raise AppError('此任务已达到40条补充说明上限，请新建任务。', 429)
            return super().add_note(tid, text, revision, scope, user_instruction)

    def snapshot(self, task, label):
        if len(self.versions(task['id'])) >= 80:
            raise AppError('此任务已达到80个历史版本上限，请新建任务。', 429)
        return super().snapshot(task, label)

    def export(self, tid, revision, kind='both'):
        with self.lock:
            if len(self.get(tid)['exports']) >= 30:
                raise AppError('此任务已达到30次文件交付上限，已有文件仍可下载。', 429)
            return super().export(tid, revision, kind)
