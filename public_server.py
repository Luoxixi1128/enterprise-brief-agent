"""Public WSGI entry point. No local data, settings mutation, or shell access."""
import json
import mimetypes
import os
import secrets
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import quote, urlparse

from core import AppError, ROOT
from model import config_status, ModelError
from public_runtime import PublicRuntime

VERSION = json.loads((ROOT / 'version.json').read_text())['version']
STATIC = {'/app.js', '/agent.js', '/background.js', '/styles.css', '/favicon.svg', '/matrix-logo.png'}


def safe_view(value):
    """Paths are server implementation details, not part of the visitor API."""
    if isinstance(value, dict):
        return {k: safe_view(v) for k, v in value.items() if k not in {'path', 'workspace_id', 'cloud_saved'}}
    if isinstance(value, list):
        return [safe_view(v) for v in value]
    return value


def make_app(root=None, secret=None, origin=None, *, testing=False, cloud_client=None):
    origin = origin or os.getenv('PUBLIC_ORIGIN') or ('https://' + os.environ['RENDER_EXTERNAL_HOSTNAME'] if os.getenv('RENDER_EXTERNAL_HOSTNAME') else '')
    backend = os.getenv('PUBLIC_STORAGE_BACKEND', 'local')
    if backend not in ('local','supabase'):
        raise RuntimeError('Unknown PUBLIC_STORAGE_BACKEND')
    if backend == 'supabase' or cloud_client is not None:
        from cloud_storage import SupabaseRuntime
        runtime = SupabaseRuntime(root or os.environ.get('BRIEF_DATA_DIR', '/tmp/brief-agent'),
                                 secret or os.environ.get('PUBLIC_SESSION_SECRET', ''), origin,
                                 testing=testing, client=cloud_client)
    else:
        runtime = PublicRuntime(root or os.environ.get('BRIEF_DATA_DIR', '/var/data/brief-agent'),
                                secret or os.environ.get('PUBLIC_SESSION_SECRET', ''), origin, testing=testing)

    def application(env, start_response):
        cookie_header = None

        def send(content, ctype='application/json; charset=utf-8', status=200, filename=None):
            if not isinstance(content, bytes):
                content = json.dumps(safe_view(content), ensure_ascii=False).encode()
            headers = [('Content-Type', ctype), ('Content-Length', str(len(content))), ('Cache-Control', 'no-store'),
                       ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'),
                       ('X-Frame-Options', 'DENY'),
                       ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
            if runtime.secure:
                headers.append(('Strict-Transport-Security', 'max-age=31536000'))
            if cookie_header:
                headers.append(('Set-Cookie', cookie_header))
            if filename:
                headers.append(('Content-Disposition', "attachment; filename*=UTF-8''" + quote(filename)))
            if status == 429:
                headers.append(('Retry-After', '60'))
            start_response(f'{status} {HTTPStatus(status).phrase}', headers)
            return [content]

        def file_response(path, name, temporary=False):
            try:
                return send(path.read_bytes(), mimetypes.guess_type(name)[0] or 'application/octet-stream', filename=name)
            finally:
                if temporary:
                    path.unlink(missing_ok=True)
                    path.parent.rmdir()

        try:
            method, path = env.get('REQUEST_METHOD', 'GET'), env.get('PATH_INFO', '/')
            # Render's health probe may use its internal hostname. It sees no data.
            if method == 'GET' and path == '/healthz':
                return send({'ok': True, 'version': VERSION})
            if env.get('HTTP_HOST') != urlparse(runtime.origin).netloc:
                raise AppError('访问地址不匹配。', 403)
            origin_header = env.get('HTTP_ORIGIN')
            if origin_header and origin_header != runtime.origin:
                raise AppError('不允许跨站请求。', 403)
            if env.get('HTTP_SEC_FETCH_SITE') == 'cross-site' and path.startswith('/api/'):
                raise AppError('不允许跨站请求。', 403)
            if method not in ('GET', 'POST'):
                raise AppError('不支持此请求方式。', 405)
            cookies = SimpleCookie()
            try:
                cookies.load(env.get('HTTP_COOKIE', ''))
            except Exception:
                pass
            token = cookies.get('brief_session')
            sid = runtime.verify(token.value if token else '')
            runtime.rate(sid, method == 'POST')
            if method == 'GET' and path in STATIC:
                f = ROOT / 'web' / path[1:]
                return send(f.read_bytes(), mimetypes.guess_type(f.name)[0] or 'text/plain')
            if method == 'GET' and path == '/':
                sid = sid or runtime.new_visitor()
                cookie_header = 'brief_session=' + runtime.cookie(sid) + '; Path=/; HttpOnly; SameSite=Lax; Max-Age=7776000' + ('; Secure' if runtime.secure else '')
                html = (ROOT / 'web/index.html').read_text().replace('__TOKEN__', runtime.csrf(sid)).replace('__PRODUCT_VERSION__', VERSION)
                return send(html.encode(), 'text/html; charset=utf-8')
            if not sid:
                raise AppError('浏览器会话已失效，请返回网站首页重新打开。', 401)
            if method == 'POST' and not secrets.compare_digest(env.get('HTTP_X_WORKSPACE_TOKEN', ''), runtime.csrf(sid)):
                raise AppError('页面会话已变化，请刷新后重试。', 403)
            if path == '/api/settings':
                raise AppError('模型由网站统一提供，访客不能修改服务配置。', 403)
            parts = path.strip('/').split('/')
            store = runtime.store(sid)
            if method == 'GET':
                if path == '/api/status':
                    return send({'application': 'enterprise-brief-agent', 'product_version': VERSION, 'skill': '0.4.3',
                                 'model': {'ready': config_status()['ready']}, 'local_only': False, 'agent_trial': False,
                                 'limits': {'daily_calls': runtime.visitor_calls, 'tasks': 20, 'file_mb': 4}})
                if path == '/api/releases':
                    return send(json.loads((ROOT / 'docs/releases/releases.json').read_text()))
                if path == '/api/releases/notes':
                    return file_response(ROOT / 'docs/releases/版本迭代总览.md', '企业需求拆解Agent-V1至V5迭代记录.md')
                if path in ('/api/tasks', '/api/trash'):
                    return send(store.list(deleted=path.endswith('trash')))
                if path == '/api/cases':
                    return send([])
                if len(parts) >= 3 and parts[:2] == ['api', 'tasks']:
                    tid = parts[2]
                    if len(parts) == 3:
                        return send(store.view(tid))
                    if len(parts) == 5 and parts[3] == 'files':
                        return file_response(*store.file(tid, parts[4]))
                    if len(parts) == 4 and parts[3] == 'data':
                        return send(json.dumps(store.get(tid)['brief'], ensure_ascii=False).encode(), filename='brief.json')
                raise AppError('页面不存在。', 404)

            if env.get('CONTENT_TYPE', '').split(';')[0] != 'application/json':
                raise AppError('请求需使用JSON。', 415)
            length = int(env.get('CONTENT_LENGTH') or 0)
            if not 0 < length <= 6_000_000:
                raise AppError('请求为空或超过大小限制。', 413)
            body = json.loads(env['wsgi.input'].read(length))
            if not isinstance(body, dict):
                raise AppError('请求需为JSON对象。')
            # Serialize admission of writes. Reserve room for parsed content and
            # small generated artifacts; existing downloads stay available at cap.
            with runtime.lock, store.lock:
                if not path.endswith('/agent-pause'):
                    runtime.storage_guard(store, length * 2 + 500_000)
                if parts == ['api', 'tasks']:
                    return send(store.new(body.get('title', ''), body.get('company', '')), status=201)
                if len(parts) != 4 or parts[:2] != ['api', 'tasks']:
                    raise AppError('操作不存在。', 404)
                tid, op = parts[2:]
                store.get(tid, include_deleted=op == 'undelete')
                rev = body.get('revision')
                if op == 'upload': result = store.add_file(tid, body.get('name', ''), body.get('data', ''))
                elif op == 'note': result = store.add_note(tid, body.get('text', ''), rev, body.get('scope_authorization', False), body.get('user_instruction', False))
                elif op == 'agent-run': result = store.start_agent(tid, rev, body.get('text', ''), body.get('resume', False), body.get('reply_to'))
                elif op == 'agent-pause': result = store.pause_agent(tid, rev)
                elif op == 'agent-confirm': result = store.confirm_agent(tid, rev)
                elif op == 'agent-answer': result = store.answer_and_continue(tid, rev, body)
                elif op == 'brief': result = store.set_brief(tid, body.get('brief'), rev)
                elif op == 'answer': result = store.answer(tid, body.get('id'), body.get('text', ''), body.get('by'), rev, body.get('selection'), body.get('approved'))
                elif op == 'review': result = store.review(tid, rev)
                elif op == 'restore': result = store.restore(tid, body.get('version'), rev)
                elif op == 'export': result = store.export(tid, rev, body.get('kind', 'both'))
                elif op == 'confirmation-add': result = store.add_confirmation(tid, body.get('topic'), body.get('question'), rev)
                elif op == 'confirmation-delete': result = store.delete_confirmation(tid, body.get('id'), rev)
                elif op == 'version-open':
                    return file_response(*store.version_document(tid, body.get('version')), temporary=True)
                elif op == 'delete': result = store.delete(tid, rev)
                elif op == 'undelete': result = store.undelete(tid)
                else: raise AppError('操作不存在。', 404)
                return send(result)
        except AppError as e:
            return send({'error': str(e)}, status=e.status)
        except ModelError:
            return send({'error': '模型暂时不可用，进度已保存，请稍后继续。'}, status=503)
        except (ValueError, TypeError, KeyError):
            return send({'error': '请求数据格式错误。'}, status=400)
        except Exception:
            return send({'error': '操作暂时未完成，已保存的任务仍然保留，请稍后重试。'}, status=500)

    application.runtime = runtime
    return application
