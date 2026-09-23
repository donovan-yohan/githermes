"""Real fake-gh subprocesses + real Hermes FastAPI registration/auth/profile scopes.
Run with HERMES_SOURCE_DIR pointing to the checkout matching the gateway.
No real GitHub credentials or configuration are read or changed.
"""
import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get('HERMES_SOURCE_DIR'):
    sys.path.insert(0, os.environ['HERMES_SOURCE_DIR'])


def module(name):
    spec = importlib.util.spec_from_file_location('test_' + name, ROOT / 'dashboard' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


FAKE_GH = '''#!/usr/bin/python3
import json, os, sys
args = sys.argv[1:]
if args[:2] == ['auth', 'status']:
    print(json.dumps([{'login':'alpha','active':True,'state':'success'}, {'login':'beta','active':False,'state':'success'}]))
elif args[:2] == ['auth', 'token']:
    assert not os.environ.get('GH_TOKEN')
    print('fake-private-' + args[args.index('--user')+1])
else:
    token = os.environ.get('GH_TOKEN', '')
    assert token not in sys.argv
    assert not any(k in os.environ for k in ['GITHUB_TOKEN', 'GH_DEBUG', 'GH_ENTERPRISE_TOKEN'])
    assert os.environ['GH_HOST'] == 'github.com'
    path = args[-1]
    if path == 'user':
        print(json.dumps({'login': token.removeprefix('fake-private-')}))
    else:
        with open(os.path.join(os.environ['GH_CONFIG_DIR'], 'calls.jsonl'), 'a') as f:
            f.write(json.dumps({'args': args, 'home': os.environ['HOME'], 'login': token.removeprefix('fake-private-')}) + '\\n')
        body = json.load(sys.stdin) if '--input' in args else None
        print(json.dumps({'login':token.removeprefix('fake-private-'), 'config':os.environ['GH_CONFIG_DIR'], 'home':os.environ['HOME'], 'body':body, 'tokenEcho':token, 'text':'日本語 🐙', 'secret':'ghp_' + 'A'*36}))
'''


@pytest.fixture
def fake(tmp_path):
    gh = tmp_path / 'gh'
    gh.write_text(FAKE_GH)
    gh.chmod(0o700)
    config = tmp_path / 'gh-config'
    config.mkdir()
    sentinel = config / 'hosts.yml'
    sentinel.write_text('fake untouched config')
    return gh, config


def test_subprocess_a_b_a_and_token_suppression(fake, tmp_path, monkeypatch):
    gh, config = fake
    for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_DEBUG', 'GH_ENTERPRISE_TOKEN'):
        monkeypatch.setenv(key, 'ambient-poison')
    before = dict(os.environ)
    backend = module('account_backend')
    executor = backend.AccountExecutor(str(gh), str(config), str(tmp_path))
    for login in ('alpha', 'beta', 'alpha'):
        result = executor.execute(login, ['repo', 'list'])
        assert result['login'] == login
        assert result['home'] == str(tmp_path)
        assert 'fake-private-' not in json.dumps(result)
    assert dict(os.environ) == before
    assert (config / 'hosts.yml').read_text() == 'fake untouched config'
    gh.write_text(FAKE_GH.replace("'fake-private-' + args[args.index('--user')+1]", "'fake-private-beta'"))
    with pytest.raises(backend.AccountError, match='account unavailable'):
        executor.execute('alpha', ['repo', 'list'])
    with pytest.raises(backend.AccountError):
        executor.execute('missing', ['repo', 'list'])


@pytest.mark.parametrize('operation', [
    {'operation':'shell', 'command':'gh auth switch'},
    {'operation':'github.api', 'path':'https://evil.test/user'},
    {'operation':'github.api', 'path':'repos/a/b/../../user'},
    {'operation':'github.api', 'path':'repos/a/b/%2e%2e/user'},
    {'operation':'github.api', 'path':'user', 'args':['--verbose']},
    {'operation':'github.api', 'path':'user', 'headers':{'Authorization':'anything'}},
    {'operation':'github.api', 'path':'user', 'method':'POST', 'body':{}},
    {'operation':'github.api', 'path':'graphql', 'method':'POST', 'body':{'query':'mutation { x }'}},
    {'operation':'pr.merge', 'repo':'a/b;touch /evil', 'number':1},
    {'operation':'pr.view', 'repo':'a/b', 'number':'--help'},
    {'operation':'pr.list', 'repo':'a/b', 'fields':'number,--template'},
    {'operation':'repo.list', 'limit':100000},
])
def test_reject_injection(operation):
    with pytest.raises(ValueError):
        module('operations').compile_operation(operation)


def test_graphql_and_comment_are_json_stdin_not_cli_flags():
    compile = module('operations').compile_operation
    body = {'body': '@file; $(touch /evil)\n日本語'}
    args, payload = compile({'operation':'github.api', 'path':'repos/a/b/issues/1/comments', 'method':'POST', 'body':body})
    assert args[-2:] == ['--input', '-'] and payload == body
    assert '@file' not in ' '.join(args)
    args, payload = compile({'operation':'github.api', 'path':'graphql', 'method':'POST', 'body':{'query':'query { viewer { login } }', 'variables':{}}})
    assert args[args.index('--hostname')+1] == 'github.com'


@pytest.fixture
def mounted(tmp_path, monkeypatch, fake):
    from hermes_cli import web_server as ws, web_server_dashboard as dashboard, plugins_cmd
    from agent import secret_scope
    from tui_gateway import launch_profile_policy
    from starlette.testclient import TestClient
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    home = tmp_path / '.hermes'
    profiles = {}
    for name in ('alpha', 'beta'):
        profile = home / 'profiles' / name
        profile.mkdir(parents=True)
        config = tmp_path / ('gh-' + name)
        config.mkdir()
        (profile / '.env').write_text(f'GH_CONFIG_DIR={config}\n')
        (profile / 'config.yaml').write_text('plugins:\n  enabled: [githermes]\n')
        profiles[name] = (profile, config)
    (home / 'config.yaml').write_text('plugins:\n  enabled: [githermes]\n')
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('GH_CONFIG_DIR', str(tmp_path / 'ambient-wrong'))
    monkeypatch.setenv('GH_TOKEN', 'ambient-token')
    monkeypatch.setattr(secret_scope, '_MULTIPLEX_ACTIVE', False)
    monkeypatch.setattr(launch_profile_policy, '_snapshot', {})
    metadata = dashboard._dashboard_plugin_entry(json.loads((ROOT / 'dashboard/manifest.json').read_text()), 'githermes', ROOT / 'dashboard', 'user')
    monkeypatch.setattr(ws, '_get_dashboard_plugins', lambda **kw: [metadata])
    monkeypatch.setattr(plugins_cmd, '_get_enabled_set', lambda: {'githermes'})
    monkeypatch.setattr(plugins_cmd, '_get_disabled_set', lambda: set())
    original = list(ws.app.router.routes)
    dashboard._mount_plugin_api_routes()
    routes = [r for r in ws.app.router.routes if r not in original]
    assert {r.path for r in routes} == {'/api/plugins/githermes/' + x for x in ('accounts', 'selection', 'operation', 'revoke')}
    ws.app.router.routes[:] = routes + original
    api = sys.modules['hermes_dashboard_plugin_githermes']
    real_which = api.shutil.which
    monkeypatch.setattr(api.shutil, 'which', lambda cmd: str(fake[0]) if cmd == 'gh' else real_which(cmd))
    client = TestClient(ws.app)
    headers = {ws._SESSION_HEADER_NAME: ws._SESSION_TOKEN}
    try:
        yield client, headers, api, profiles
    finally:
        client.close()
        ws.app.router.routes[:] = original


def call(client, headers, route, profile='alpha', body=None):
    path = f'/api/plugins/githermes/{route}?profile={profile}'
    return client.get(path, headers=headers) if body is None else client.post(path, headers=headers, json=body)


def test_real_registration_auth_profile_epoch_and_redaction(mounted):
    client, headers, api, profiles = mounted
    assert call(client, {}, 'accounts').status_code == 401
    assert call(client, headers, 'accounts').json()['accounts'][1]['login'] == 'beta'
    selected = call(client, headers, 'selection', body={'login':'alpha'}).json()
    def op(selection, profile='alpha'):
        return call(client, headers, 'operation', profile, {k:selection[k] for k in ('lease','epoch')} | {'operation':{'operation':'repo.list','fields':'nameWithOwner'}})
    before = dict(os.environ)
    result = op(selected)
    assert result.status_code == 200, result.text
    data = result.json()['data']
    assert data['login'] == 'alpha'
    assert data['home'] == str(profiles['alpha'][0])
    assert data['config'] == str(profiles['alpha'][1])
    assert data['text'] == '日本語 🐙'
    assert 'fake-private-' not in result.text and 'ghp_' + 'A'*36 not in result.text
    comment = {'body': '@file; $(touch /must-not-exist)\n日本語 🐙'}
    posted = call(client, headers, 'operation', body={k:selected[k] for k in ('lease','epoch')} | {'operation':{'operation':'github.api','path':'repos/a/b/issues/1/comments','method':'POST','body':comment}})
    assert posted.status_code == 200, posted.text
    assert posted.json()['data']['body'] == comment
    assert op(selected, 'beta').status_code == 409
    old = selected
    selected = call(client, headers, 'selection', body={'login':'beta','lease':old['lease'],'epoch':old['epoch']}).json()
    assert op(old).status_code == 409
    assert op(selected).json()['data']['login'] == 'beta'
    newer = call(client, headers, 'selection', 'beta', {'login':'alpha','lease':selected['lease'],'epoch':selected['epoch']}).json()
    assert op(selected).status_code == 409
    result = op(newer, 'beta').json()['data']
    assert result['login'] == 'alpha' and result['config'] == str(profiles['beta'][1])
    final = call(client, headers, 'selection', 'alpha', {'login':'alpha','lease':newer['lease'],'epoch':newer['epoch']}).json()
    assert op(newer, 'beta').status_code == 409
    final_data = op(final).json()['data']
    assert final_data['config'] == str(profiles['alpha'][1]) and final_data['login'] == 'alpha'
    assert dict(os.environ) == before
    assert client.post('/api/plugins/githermes/operation?profile=beta', headers=headers, content='x'*(api.operations.MAX_BODY + 1)).status_code == 413
    assert client.get('/api/plugins/githermes/accounts', headers=headers).status_code == 422
    assert call(client, headers, 'accounts', '').status_code == 400
    assert call(client, headers, 'accounts', 'current').status_code == 400


def test_stale_write_rechecked_after_private_identity_resolution(mounted, monkeypatch):
    client, headers, api, profiles = mounted
    selected = call(client, headers, 'selection', body={'login':'alpha'}).json()
    arrived, release = threading.Event(), threading.Event()
    original = api.backend.AccountExecutor._run
    def delayed(self, args, env, body=None):
        result = original(self, args, env, body)
        if args[-1] == 'user':
            arrived.set()
            assert release.wait(10)
        return result
    monkeypatch.setattr(api.backend.AccountExecutor, '_run', delayed)
    payload = {k:selected[k] for k in ('lease','epoch')} | {'operation':{'operation':'issue.close','repo':'a/b','number':1}}
    with concurrent.futures.ThreadPoolExecutor() as pool:
        pending = pool.submit(call, client, headers, 'operation', 'alpha', payload)
        assert arrived.wait(10)
        changed = call(client, headers, 'selection', body={'login':'beta', 'lease':selected['lease'], 'epoch':selected['epoch']})
        assert changed.status_code == 200, changed.text
        release.set()
        assert pending.result().status_code == 409
    assert not (profiles['alpha'][1] / 'calls.jsonl').exists()


def test_runtime_disabled_and_missing_profile_config_fail_closed(mounted, monkeypatch):
    client, headers, api, profiles = mounted
    from hermes_cli import plugins_cmd
    monkeypatch.setattr(plugins_cmd, '_get_disabled_set', lambda: {'githermes'})
    assert call(client, headers, 'accounts').status_code == 404
    monkeypatch.setattr(plugins_cmd, '_get_disabled_set', lambda: set())
    profile = profiles['alpha'][0].parent / 'unconfigured'
    profile.mkdir()
    (profile / 'config.yaml').write_text('{}')
    response = call(client, headers, 'accounts', 'unconfigured')
    assert response.status_code == 400
    assert response.json()['detail'] == 'Configure GH_CONFIG_DIR for this profile'


def test_timeout_covers_a_child_that_never_reads_json_stdin(fake):
    gh, config = fake
    backend = module('account_backend')
    backend.COMMAND_TIMEOUT = 0.1
    gh.write_text('#!/usr/bin/python3\nimport time\ntime.sleep(10)\n')
    executor = backend.AccountExecutor(str(gh), str(config))
    with pytest.raises(backend.AccountError, match='timed out'):
        executor._run(['api', 'graphql', '--input', '-'], executor.env, {'query':'x' * 200000})


def test_output_limit_and_fixed_child_error(fake):
    gh, config = fake
    backend = module('account_backend')
    gh.write_text(FAKE_GH.replace("    path = args[-1]", "    path = args[-1]\n    if path != 'user':\n        print(token, file=sys.stderr)\n        sys.exit(1)"))
    with pytest.raises(backend.AccountError, match='^GitHub command failed$'):
        backend.AccountExecutor(str(gh), str(config)).execute('alpha', ['repo', 'list'])
    gh.write_text('#!/usr/bin/python3\nprint("x" * (5*1024*1024))\n')
    with pytest.raises(backend.AccountError, match='too large'):
        backend.AccountExecutor(str(gh), str(config)).accounts()
