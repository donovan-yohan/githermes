"""Real HTTP against two independent backend processes, real auth + fake gh."""
import concurrent.futures
import multiprocessing
import os
import socket
import time
from pathlib import Path

import httpx
import pytest
from test_account_backend import mounted, fake, call, FAKE_GH


def serve(fd, home):
    import uvicorn
    from hermes_cli import web_server as ws
    os.environ['HERMES_HOME'] = str(home)
    # Deliberately wrong ambient config in the profile process as well.
    os.environ['GH_CONFIG_DIR'] = '/ambient-not-profile'
    uvicorn.Server(uvicorn.Config(ws.app, log_level='error', lifespan='off')).run(sockets=[socket.socket(fileno=fd)])


@pytest.fixture
def servers(mounted):
    client, headers, api, profiles = mounted
    ctx = multiprocessing.get_context('fork')
    processes, sockets, clients = [], [], []
    try:
        for home in (profiles['alpha'][0].parent.parent, profiles['beta'][0]):
            sock = socket.socket()
            sock.bind(('127.0.0.1', 0)); sock.listen(64)
            process = ctx.Process(target=serve, args=(sock.fileno(), home))
            process.start()
            connection = httpx.Client(base_url=f'http://127.0.0.1:{sock.getsockname()[1]}', timeout=15)
            processes.append(process); sockets.append(sock); clients.append(connection)
            index = len(processes) - 1
            def restart(index=index, sock=sock, home=home):
                old = processes[index]
                old.terminate(); old.join(5)
                replacement = ctx.Process(target=serve, args=(sock.fileno(), home))
                replacement.start()
                processes[index] = replacement
                assert replacement.pid != old.pid
            connection.restart_backend = restart
            for _ in range(100):
                try:
                    if call(connection, {}, 'accounts').status_code == 401:
                        break
                except httpx.TransportError:
                    time.sleep(.02)
            else:
                pytest.fail('HTTP server did not start')
        yield clients, headers, profiles
    finally:
        for client in clients: client.close()
        for process in processes:
            process.terminate(); process.join(5)
        for sock in sockets: sock.close()


def operation(client, headers, selection, profile='alpha'):
    return call(client, headers, 'operation', profile, {k: selection[k] for k in ('lease', 'epoch')} | {'operation': {'operation': 'issue.close', 'repo': 'a/b', 'number': 1}})


def test_cross_process_http_authority_and_profile_credentials(servers):
    (a, b), headers, profiles = servers
    discovered = call(a, headers, 'accounts').json()
    first = call(b, headers, 'selection', body={'login': 'alpha'}).json()
    assert first['backend'] == discovered['backend'], 'authority must be shared, not a process nonce'
    result = operation(a, headers, first)
    assert result.status_code == 200, result.text
    assert result.json()['data']['config'] == str(profiles['alpha'][1])
    independent = call(a, headers, 'selection', body={'login': 'alpha'}).json()
    changed = call(a, headers, 'selection', 'beta', {'lease': first['lease'], 'epoch': first['epoch'], 'login': 'beta'}).json()
    assert operation(b, headers, first).status_code == 409
    result = operation(b, headers, changed, 'beta')
    assert result.status_code == 200, result.text
    assert result.json()['data']['config'] == str(profiles['beta'][1])
    assert operation(b, headers, independent).status_code == 200
    b.restart_backend()
    assert operation(b, headers, changed, 'beta').status_code == 200
    revoked = call(b, headers, 'revoke', 'alpha', {k: changed[k] for k in ('lease', 'epoch')})
    assert revoked.status_code == 200
    assert operation(a, headers, changed, 'beta').status_code == 409
    assert 'fake-private-' not in result.text


def test_delayed_identity_cannot_dispatch_after_other_process_switch(servers, fake):
    (a, b), headers, profiles = servers
    gh, _ = fake
    gh.write_text(FAKE_GH.replace("    if path == 'user':", "    if path == 'user':\n        import time\n        from pathlib import Path\n        root = Path(os.environ['GH_CONFIG_DIR'])\n        (root / 'arrived').touch()\n        while not (root / 'release').exists(): time.sleep(.01)"))
    selected = call(a, headers, 'selection', body={'login': 'alpha'}).json()
    config = profiles['alpha'][1]
    with concurrent.futures.ThreadPoolExecutor() as pool:
        pending = pool.submit(operation, a, headers, selected)
        try:
            for _ in range(500):
                if (config / 'arrived').exists(): break
                time.sleep(.01)
            else: pytest.fail('identity verification not reached')
            switched = call(b, headers, 'selection', 'beta', {'lease': selected['lease'], 'epoch': selected['epoch'], 'login': 'beta'})
            assert switched.status_code == 200, switched.text
        finally:
            (config / 'release').touch()
        assert pending.result().status_code == 409
    assert not (config / 'calls.jsonl').exists()


def test_unknown_revoke_is_authoritative_and_restart_preserves_lease(mounted):
    client, headers, api, profiles = mounted
    selected = call(client, headers, 'selection', body={'login': 'alpha'}).json()
    from test_account_backend import module
    restarted = module('plugin_api')
    assert restarted.work('alpha', {k: selected[k] for k in ('lease', 'epoch')} | {'operation': {'operation': 'repo.list'}}, 'execute')['data']['login'] == 'alpha'
    unknown = call(client, headers, 'revoke', body={'lease': 'x' * 43, 'epoch': 1})
    assert unknown.status_code == 200, unknown.text
    assert unknown.json()['reset'] is True


def test_reviewer_renderer_probe_with_real_http(servers, fake):
    import json
    import subprocess
    from test_account_backend import ROOT
    clients, headers, profiles = servers
    gh, _ = fake
    gh.write_text(FAKE_GH.replace("    if path == 'user':", "    if path == 'user':\n        import time\n        from pathlib import Path\n        root = Path(os.environ['GH_CONFIG_DIR'])\n        (root / 'arrived').touch()\n        while not (root / 'release').exists(): time.sleep(.01)"))
    result = subprocess.run(['node', str(ROOT / 'scripts/http-account-probe.mjs')], input=json.dumps({'urls': [str(c.base_url).rstrip('/') for c in clients], 'headers': headers, 'config': str(profiles['beta'][1])}), text=True, capture_output=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'GREEN:' in result.stdout


def test_unknown_revoke_tombstone_fences_lost_initial_selection(mounted):
    client, headers, api, profiles = mounted
    key = 'x' * 43
    revoked = call(client, headers, 'revoke', body={'lease': key, 'epoch': 0}).json()
    assert call(client, headers, 'selection', body={'lease': key, 'epoch': 0, 'login': 'alpha'}).status_code == 409
    selected = call(client, headers, 'selection', body={'lease': key, 'epoch': revoked['epoch'], 'login': 'beta'})
    assert selected.status_code == 200
    assert operation(client, headers, selected.json()).json()['data']['login'] == 'beta'


def test_expired_selection_can_be_revoked_and_reselected(mounted):
    client, headers, api, profiles = mounted
    selected = call(client, headers, 'selection', body={'login': 'alpha'}).json()
    with api.authority.locked() as store:
        store.db.execute('UPDATE leases SET touched=0')
    assert operation(client, headers, selected).status_code == 409
    revoked = call(client, headers, 'revoke', body={k: selected[k] for k in ('lease', 'epoch')}).json()
    changed = call(client, headers, 'selection', body=revoked | {'login': 'beta'})
    assert changed.status_code == 200, changed.text
    assert operation(client, headers, selected).status_code == 409


def test_failed_selection_still_revokes_previous_account(mounted):
    client, headers, api, profiles = mounted
    selected = call(client, headers, 'selection', body={'login': 'alpha'}).json()
    failed = call(client, headers, 'selection', body={k: selected[k] for k in ('lease', 'epoch')} | {'login': 'missing'})
    assert failed.status_code == 400
    assert operation(client, headers, selected).status_code == 409


def test_dispatch_fence_survives_backend_crash_until_child_exit(mounted, fake):
    client, headers, api, profiles = mounted
    gh, _ = fake
    gh.write_text(FAKE_GH.replace("    else:\n        with open", "    else:\n        import time\n        from pathlib import Path\n        root = Path(os.environ['GH_CONFIG_DIR'])\n        (root / 'dispatch-arrived').touch()\n        while not (root / 'dispatch-release').exists(): time.sleep(.01)\n        with open"))
    selected = call(client, headers, 'selection', body={'login': 'alpha'}).json()
    payload = {k: selected[k] for k in ('lease', 'epoch')} | {'operation': {'operation': 'issue.close', 'repo': 'a/b', 'number': 1}}
    worker = multiprocessing.get_context('fork').Process(target=api.work, args=('alpha', payload, 'execute'))
    config = profiles['alpha'][1]
    worker.start()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        try:
            for _ in range(500):
                if (config / 'dispatch-arrived').exists(): break
                time.sleep(.01)
            else: pytest.fail('dispatch not reached')
            pending = pool.submit(call, client, headers, 'revoke', 'alpha', {k: selected[k] for k in ('lease', 'epoch')})
            time.sleep(.15)
            assert not pending.done(), 'revoke overtook already-dispatched child'
            worker.kill(); worker.join(5)
            time.sleep(.15)
            assert not pending.done(), 'backend death released a live child fence'
        finally:
            (config / 'dispatch-release').touch()
            if worker.is_alive(): worker.kill()
            worker.join(5)
        assert pending.result(timeout=10).status_code == 200
    assert operation(client, headers, selected).status_code == 409
    assert (config / 'calls.jsonl').exists()


def test_orphan_deadline_reaps_child_and_releases_same_fence(mounted, fake, monkeypatch):
    client, headers, api, profiles = mounted
    gh, _ = fake
    gh.write_text(FAKE_GH.replace("    else:\n        with open", "    else:\n        import time\n        from pathlib import Path\n        root = Path(os.environ['GH_CONFIG_DIR'])\n        (root / 'child-pid').write_text(str(os.getpid()))\n        while True: time.sleep(.01)\n        with open"))
    selected = call(client, headers, 'selection', body={'login': 'alpha'}).json()
    monkeypatch.setattr(api.backend, 'COMMAND_TIMEOUT', 2)
    payload = {k: selected[k] for k in ('lease', 'epoch')} | {'operation': {'operation': 'issue.close', 'repo': 'a/b', 'number': 1}}
    worker = multiprocessing.get_context('fork').Process(target=api.work, args=('alpha', payload, 'execute'))
    config = profiles['alpha'][1]
    fence = profiles['alpha'][0].parent.parent / 'githermes-authority' / 'fence.lock'
    inode = fence.stat().st_ino
    child = None
    worker.start()
    try:
        for _ in range(500):
            if (config / 'child-pid').exists(): break
            time.sleep(.01)
        else: pytest.fail('dispatch not reached')
        child = int((config / 'child-pid').read_text())
        worker.kill(); worker.join(5)
        import fcntl
        with fence.open() as probe:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    assert time.monotonic() < deadline, 'orphan retained fence past autonomous deadline'
                    time.sleep(.02)
            # Reaped, not merely a zombie that no longer holds descriptors.
            with pytest.raises(ProcessLookupError): os.kill(child, 0)
        assert fence.stat().st_ino == inode
        revoked = call(client, headers, 'revoke', body={k: selected[k] for k in ('lease', 'epoch')})
        assert revoked.status_code == 200
        assert operation(client, headers, selected).status_code == 409
        assert not (config / 'calls.jsonl').exists()
    finally:
        if worker.is_alive(): worker.kill()
        worker.join(5)
        if child is not None:
            try: os.kill(child, 9)
            except ProcessLookupError: pass


def test_private_store_permissions_and_bounded_cleanup(mounted):
    client, headers, api, profiles = mounted
    selected = call(client, headers, 'selection', body={'login': 'alpha'}).json()
    directory = profiles['alpha'][0].parent.parent / 'githermes-authority'
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / 'leases.sqlite3').stat().st_mode & 0o777 == 0o600
    assert (directory / 'fence.lock').stat().st_mode & 0o777 == 0o600
    with api.authority.locked() as store:
        store.db.execute('UPDATE leases SET touched=0')
    call(client, headers, 'selection', body={'login': 'beta'})
    with api.authority.locked() as store:
        assert store.db.execute('SELECT count(*) FROM leases').fetchone()[0] == 1
        assert store.get(selected['lease']) is None
    (directory / 'fence.lock').chmod(0o644)
    assert call(client, headers, 'accounts').status_code == 503
