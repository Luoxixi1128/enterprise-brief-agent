import os

bind = '0.0.0.0:' + os.environ.get('PORT', '10000')
workers = 1
worker_class = 'gthread'
threads = 4
timeout = 180
graceful_timeout = 30
# Long model calls run in background threads. Never recycle the worker while
# those threads own AgentStore state; an interrupted deploy is resumable.
max_requests = 0
preload_app = False
accesslog = None
errorlog = '-'
