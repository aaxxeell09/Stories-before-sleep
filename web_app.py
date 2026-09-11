"""Local StorySprout UI. Run with python3 web_app.py."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
KEYS = ('ROCKETRIDE_URI', 'ROCKETRIDE_APIKEY', 'ROCKETRIDE_OPENAI_KEY')
MEMORY_KEYS = ('COGNEE_BASE_URL', 'COGNEE_API_KEY', 'HYDRA_DB_API_KEY', 'HYDRA_DB_TENANT_ID')


def config():
    values = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('\"\'')
    values.update(os.environ)
    return values


def missing(keys):
    values = config()
    return [key for key in keys if not values.get(key) or values[key].startswith('replace-with-') or 'your-cognee-instance' in values[key]]


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('Expected an object.')
    kind = data.get('kind')
    if kind not in ('generate', 'memory'):
        raise ValueError('Unknown action.')
    fields = {'lesson': 2000, 'characters': 500} if kind == 'generate' else {'dataset': 100, 'query': 2000, 'story': 20000}
    result = {'kind': kind}
    for name, limit in fields.items():
        value = data.get(name, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f'{name} must be text of at most {limit} characters.')
        result[name] = value.strip()
    if kind == 'generate':
        if type(data.get('age')) is not int or not 0 <= data['age'] <= 18:
            raise ValueError('Age must be a whole number between 0 and 18.')
        if data.get('minutes') not in (2, 5, 8) or type(data.get('rhyme')) is not bool:
            raise ValueError('Choose a reading length and rhyme setting.')
        if not result['lesson']:
            raise ValueError('Add a lesson first.')
        result.update(age=data['age'], minutes=data['minutes'], rhyme=data['rhyme'])
    elif not result['dataset'] or not result['query']:
        raise ValueError('Dataset and recall question are required.')
    return result


class App(ThreadingHTTPServer):
    def __init__(self, address):
        super().__init__(address, Handler)
        self.jobs = {}
        self.lock = threading.Lock()

    def run_job(self, job_id, payload):
        try:
            process = subprocess.run([sys.executable, str(ROOT / 'web_worker.py')], input=json.dumps(payload), text=True, capture_output=True, cwd=ROOT, timeout=1200)
            result = json.loads(process.stdout)
            if process.returncode:
                raise RuntimeError(result.get('error', 'Operation failed.'))
            job = {'status': 'complete', 'result': result}
        except subprocess.TimeoutExpired:
            job = {'status': 'failed', 'error': 'The operation timed out. A memory write may have completed; check data/ before retrying.'}
        except Exception as exc:
            message = str(exc) if isinstance(exc, RuntimeError) else 'The worker could not finish. Check dependencies and server configuration.'
            job = {'status': 'failed', 'error': message}
        with self.lock:
            self.jobs[job_id] = job


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, content_type='application/json'):
        content = json.dumps(body).encode() if content_type == 'application/json' else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(content)

    def allowed(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        return self.headers.get('Host') == expected and self.headers.get('Origin', f'http://{expected}') == f'http://{expected}'

    def do_GET(self):
        if not self.allowed():
            return self.reply(403, {'error': 'Open this app using its 127.0.0.1 URL.'})
        if self.path == '/api/status':
            age = 3
            try:
                saved = json.loads((ROOT / 'data/child-profile.json').read_text()).get('age', 3)
                if type(saved) is int and 0 <= saved <= 18:
                    age = saved
            except (OSError, ValueError, AttributeError):
                pass
            return self.reply(200, {'generation_missing': missing(KEYS), 'memory_missing': missing(KEYS + MEMORY_KEYS), 'age': age})
        if self.path.startswith('/api/jobs/'):
            with self.server.lock:
                job = self.server.jobs.get(self.path.split('/')[-1])
            return self.reply(200 if job else 404, job or {'error': 'Job not found. The server may have restarted.'})
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.path not in assets:
            return self.reply(404, {'error': 'Not found'})
        name, mime = assets[self.path]
        self.reply(200, (ROOT / 'web' / name).read_bytes(), mime)

    def do_POST(self):
        if not self.allowed() or self.headers.get('Content-Type') != 'application/json':
            return self.reply(403, {'error': 'Only same-origin JSON requests are accepted.'})
        if self.path != '/api/jobs':
            return self.reply(404, {'error': 'Not found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 100000:
                raise ValueError('Request is empty or too large.')
            payload = validate(json.loads(self.rfile.read(length)))
            absent = missing(KEYS if payload['kind'] == 'generate' else KEYS + MEMORY_KEYS)
            if absent:
                raise ValueError('Configure these values in .env: ' + ', '.join(absent))
        except (ValueError, UnicodeError) as exc:
            return self.reply(400, {'error': str(exc)})
        with self.server.lock:
            if any(job['status'] == 'running' for job in self.server.jobs.values()):
                return self.reply(409, {'error': 'An operation is already running. Please wait for it to finish.'})
            job_id = uuid4().hex
            if len(self.server.jobs) >= 100:
                del self.server.jobs[next(iter(self.server.jobs))]
            self.server.jobs[job_id] = {'status': 'running'}
        threading.Thread(target=self.server.run_job, args=(job_id, payload), daemon=True).start()
        self.reply(202, {'id': job_id})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    with App(('127.0.0.1', args.port)) as server:
        print(f'StorySprout: http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
