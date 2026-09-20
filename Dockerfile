FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BRIEF_DATA_DIR=/tmp/brief-agent PUBLIC_STORAGE_BACKEND=supabase PORT=10000
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home app
COPY core.py agent_runtime.py model.py content_audit.py confirmation_actions.py public_runtime.py public_server.py cloud_storage.py wsgi.py gunicorn.conf.py version.json ./
COPY web ./web
COPY prompts ./prompts
COPY vendor ./vendor
COPY docs/releases ./docs/releases
USER app
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/healthz',timeout=4)"
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
