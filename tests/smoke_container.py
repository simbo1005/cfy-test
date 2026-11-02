"""Start the actual built image on CPU and verify both interfaces before publishing."""
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

IMAGE = os.environ.get('SMOKE_IMAGE', 'cfy:check')
NAME = 'cfy-startup-check'
ORIGIN = 'https://smoketest-8888.proxy.runpod.net'
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def request(port, path, method='GET', payload=None, proxy=False):
    headers = {}
    if proxy:
        headers = {'Origin': ORIGIN, 'Host': '127.0.0.1:60940', 'X-Forwarded-Proto': 'https',
                   'Cookie': '; '.join(f'{c.name}={c.value}' for c in jar)}
        for cookie in jar:
            if cookie.name == '_xsrf':
                headers['X-XSRFToken'] = cookie.value
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', method=method, headers=headers,
                                 data=json.dumps(payload).encode() if payload is not None else None)
    with opener.open(req, timeout=10) as response:
        raw = response.read()
        return response.status, raw


def wait_for(port, path, proxy=False):
    deadline = time.monotonic() + 300
    last = None
    while time.monotonic() < deadline:
        try:
            return request(port, path, proxy=proxy)
        except Exception as exc:
            last = exc
            time.sleep(2)
    raise RuntimeError(f'{port}{path} did not become ready: {last}')


manifest = Path(__file__).with_name('empty-models.json').resolve()
subprocess.run(['docker', 'run', '-d', '--name', NAME,
                '-p', '127.0.0.1:8188:8188', '-p', '127.0.0.1:8888:8888',
                '-e', 'RUNPOD_POD_ID=smoketest', '-e', 'JUPYTER_TOKEN=',
                '-e', 'MODEL_MANIFEST=/tmp/empty-models.json',
                '-v', f'{manifest}:/tmp/empty-models.json:ro', IMAGE,
                '/bin/bash', '/opt/template/start.sh', '--cpu', '--disable-partner-nodes'], check=True)
try:
    wait_for(8888, '/lab', proxy=True)
    wait_for(8188, '/system_stats')
    status, body = request(8188, '/object_info/LocalPromptFormatter')
    assert status == 200 and 'LocalPromptFormatter' in json.loads(body), 'Local formatter did not load'
    status, body = request(8888, '/api/terminals', 'POST', {}, proxy=True)
    assert status == 200, 'Terminal creation failed'
    terminal = json.loads(body)['name']
    status, body = request(8888, '/api/contents', 'POST', {'type': 'notebook'}, proxy=True)
    assert status == 201, 'Notebook creation failed'
    notebook = json.loads(body)['path']
    status, body = request(8888, '/api/sessions', 'POST',
                           {'path': notebook, 'type': 'notebook', 'kernel': {'name': 'python3'}}, proxy=True)
    assert status == 201, 'Python kernel/session creation failed'
    session = json.loads(body)['id']
    status, body = request(8888, '/lab/api/workspaces/default', 'PUT',
                           {'data': {}, 'metadata': {'id': 'default'}}, proxy=True)
    assert status == 204, 'Workspace save failed'
    request(8888, '/api/sessions/' + session, 'DELETE', proxy=True)
    request(8888, '/api/terminals/' + terminal, 'DELETE', proxy=True)
    print('PASS: actual ComfyUI CPU server, local formatter, Jupyter terminal, notebook, kernel, and proxy workspace save.', flush=True)
finally:
    subprocess.run(['docker', 'logs', NAME], check=False)
    subprocess.run(['docker', 'rm', '-f', NAME], check=False)
