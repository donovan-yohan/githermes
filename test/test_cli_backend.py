"""Exercise the actual CLI startup/manifest loader, never manual route mounting.

HERMES_SOURCE_DIR selects a host checkout; run with that host's Python environment.
Only scratch homes, synthetic gh and loopback HTTP are used.
"""
import contextlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = os.environ.get('HERMES_SOURCE_DIR')
pytestmark = pytest.mark.skipif(not SOURCE, reason='set HERMES_SOURCE_DIR to test a real host')


@contextlib.contextmanager
def backend(tmp_path, mode='serve', enabled=True, packaged=True, profile_launch=False,
            package_in_other_profile=False):
    home = tmp_path / 'home'
    root = home / '.hermes'
    root.mkdir(parents=True)
    config = 'plugins:\n  enabled: ' + ('[githermes]' if enabled else '[]') + '\n'
    (root / 'config.yaml').write_text(config)
    for name in ('alpha', 'beta'):
        profile = root / 'profiles' / name
        profile.mkdir(parents=True)
        (profile / 'config.yaml').write_text(config)
        gh_config = profile / 'gh-config'
        gh_config.mkdir()
        (profile / '.env').write_text(f'GH_CONFIG_DIR={gh_config}\n')
    launch = root / 'profiles' / 'alpha' if profile_launch else root
    package_home = root / 'profiles' / 'beta' if package_in_other_profile else launch
    if packaged:
        shutil.copytree(ROOT / 'dashboard', package_home / 'plugins/githermes/dashboard')
        shutil.copy2(ROOT / 'plugin.yaml', package_home / 'plugins/githermes/plugin.yaml')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    gh = bin_dir / 'gh'
    gh.write_text('''#!/usr/bin/python3
import json, os, sys
args = sys.argv[1:]
config = os.environ['GH_CONFIG_DIR']
with open(config + '/audit.jsonl', 'a') as f:
    f.write(json.dumps(args[:2]) + '\\n')
if args[:2] == ['auth', 'status']:
    print(json.dumps([{'login':'fixture','active':True,'state':'success'}]))
elif args[:2] == ['auth', 'token']:
    print('synthetic-private-fixture')
elif args[-1] == 'user':
    assert os.environ['GH_TOKEN'] == 'synthetic-private-fixture'
    print(json.dumps({'login':'fixture'}))
else:
    assert os.environ['GH_TOKEN'] == 'synthetic-private-fixture'
    print(json.dumps({'home':os.environ['HOME'],'config':config}))
''')
    gh.chmod(0o700)
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'assets').mkdir()
    (dist / 'index.html').write_text('<html><head></head><body>fixture UI</body></html>')
    ready = tmp_path / 'ready.json'
    token = secrets.token_urlsafe(32)
    # Deliberately do not inherit credentials, profile selection, or live config.
    env = {k: os.environ[k] for k in ('LANG', 'LC_ALL', 'TMPDIR') if k in os.environ}
    env.update(HOME=str(home), HERMES_REAL_HOME=str(home), HERMES_HOME=str(launch),
               PATH=str(bin_dir) + ':/usr/bin:/bin', PYTHONPATH=str(SOURCE),
               HERMES_DESKTOP='1', HERMES_DASHBOARD_SESSION_TOKEN=token,
               HERMES_DESKTOP_READY_FILE=str(ready), HERMES_WEB_DIST=str(dist))
    # Reuse host dependencies without executing editable-install .pth finders:
    # those can silently import absent modules from a DIFFERENT host checkout.
    dependencies = [p for p in sys.path if p.endswith(('site-packages', 'dist-packages'))]
    bootstrap = ('import sys,runpy; sys.path.extend(' + repr(dependencies) + '); '
                 'runpy.run_module("hermes_cli.main", run_name="__main__")')
    args = [sys.executable, '-S', '-c', bootstrap, mode, '--isolated', '--port', '0']
    if mode == 'dashboard':
        args += ['--no-open']
    log_path = tmp_path / 'server.log'
    with log_path.open('w') as log:
        proc = subprocess.Popen(args, cwd=SOURCE, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 60
            while not ready.exists():
                if proc.poll() is not None or time.monotonic() > deadline:
                    pytest.fail('CLI startup failed: ' + log_path.read_text()[-6000:])
                time.sleep(.05)
            url = 'http://127.0.0.1:' + str(json.loads(ready.read_text())['port'])
            def request(path, body=None, auth=True):
                headers = {'X-Hermes-Session-Token': token} if auth else {}
                if body is not None:
                    headers['Content-Type'] = 'application/json'
                req = urllib.request.Request(url + path, headers=headers,
                                             data=None if body is None else json.dumps(body).encode())
                try:
                    with urllib.request.urlopen(req, timeout=15) as response:
                        return response.status, response.read().decode()
                except urllib.error.HTTPError as exc:
                    return exc.code, exc.read().decode()
            yield request, root
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


@pytest.mark.parametrize('mode', ['serve', 'dashboard'])
@pytest.mark.parametrize('profile_launch', [False, True])
def test_cli_loader_authenticated_accounts_and_profile_execution(tmp_path, mode, profile_launch):
    with backend(tmp_path, mode, profile_launch=profile_launch) as (request, root):
        path = '/api/plugins/githermes/accounts?profile=alpha'
        assert request(path, auth=False)[0] == 401
        for action in ('selection', 'operation', 'revoke'):
            assert request('/api/plugins/githermes/' + action + '?profile=alpha',
                           {}, auth=False)[0] == 401
        status, text = request(path)
        assert status == 200, text
        assert json.loads(text)['accounts'][0]['login'] == 'fixture'
        for profile in ('alpha', 'beta', 'alpha'):
            status, text = request('/api/plugins/githermes/selection?profile=' + profile,
                                   {'login': 'fixture'})
            assert status == 200, text
            lease = json.loads(text)
            status, text = request('/api/plugins/githermes/operation?profile=' + profile,
                                   {'lease': lease['lease'], 'epoch': lease['epoch'],
                                    'operation': {'operation': 'repo.list', 'limit': 1}})
            assert status == 200, text
            data = json.loads(text)['data']
            assert data['home'] == str(root / 'profiles' / profile)
            assert data['config'] == str(root / 'profiles' / profile / 'gh-config')
            assert 'synthetic-private' not in text
        assert request('/api/plugins/githermes/accounts?profile=missing')[0] == 404
        assert request('/api/plugins/githermes/accounts?profile=current')[0] == 400
        assert (root / 'profiles/alpha/gh-config/audit.jsonl').exists()
        # Non-root SPA route: newer serve has a token-only root handshake.
        status, text = request('/fixture-page')
        assert status == (404 if mode == 'serve' else 200)
        assert ('web UI disabled' in text) == (mode == 'serve')


@pytest.mark.parametrize('other_profile', [False, True])
def test_headless_missing_package_reproduces_reported_fallback(tmp_path, other_profile):
    with backend(tmp_path, packaged=other_profile,
                 package_in_other_profile=other_profile) as (request, _):
        status, text = request('/api/plugins/githermes/accounts?profile=alpha')
        assert status == 404
        assert 'Headless backend (hermes serve): web UI disabled' in text


def test_headless_disabled_package_is_not_imported(tmp_path):
    with backend(tmp_path, enabled=False) as (request, root):
        assert request('/api/plugins/githermes/accounts?profile=alpha')[0] == 404
        assert not (root / 'profiles/alpha/gh-config/audit.jsonl').exists()
