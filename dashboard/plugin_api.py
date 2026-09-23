"""Mounted by Hermes' authenticated /api/plugins/githermes router loader."""
import importlib.util
import json
from pathlib import Path
import secrets
import shutil
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool


def sibling(name):
    spec = importlib.util.spec_from_file_location('githermes_' + name, Path(__file__).with_name(name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backend = sibling('account_backend')
operations = sibling('operations')
router = APIRouter()
_lock = threading.RLock()
_leases = {}
TTL = 3600
BACKEND_INSTANCE = secrets.token_urlsafe(24)


def scope(profile):
    from hermes_cli.web_server_profiles import _config_profile_scope
    return _config_profile_scope(profile)


def executor():
    from hermes_constants import get_hermes_home
    from agent.secret_scope import get_secret
    # Resolve AFTER request scope entry; never use process GH_CONFIG_DIR/HOME.
    home = str(get_hermes_home().resolve())
    config = get_secret('GH_CONFIG_DIR')
    executable = shutil.which('gh')
    if not config or not Path(config).is_absolute() or not executable:
        raise backend.AccountError('Configure GH_CONFIG_DIR for this profile')
    return home, backend.AccountExecutor(str(Path(executable).resolve()), config, home=home)


def redact(value):
    from agent.redact import redact_sensitive_text
    if isinstance(value, str):
        return redact_sensitive_text(value, force=True)
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {redact(k): redact(v) for k, v in value.items()}
    return value


def check(lease_id, home, epoch=None):
    lease = _leases.get(lease_id) if isinstance(lease_id, str) else None
    if not lease or lease['home'] != home or time.monotonic() - lease['touched'] > TTL or (epoch is not None and lease['epoch'] != epoch):
        raise HTTPException(409, 'GitHub account scope changed')
    lease['touched'] = time.monotonic()
    return lease


def work(profile, data, route):
    if not isinstance(profile, str) or not profile.strip() or profile == 'current':
        raise HTTPException(400, 'Explicit GitHub profile required')
    try:
        with scope(profile):
            if route == 'revoke':
                if set(data) != {'lease', 'epoch'} or type(data.get('epoch')) is not int:
                    raise ValueError()
                with _lock:
                    lease = _leases.get(data.get('lease'))
                    if not lease or lease['epoch'] != data.get('epoch'):
                        raise HTTPException(409, 'GitHub account scope changed')
                    lease['epoch'] += 1
                    lease['login'] = None
                    return {k: lease[k] for k in ('lease', 'epoch')}
            home, gh = executor()
            if route == 'accounts':
                return {'accounts': gh.accounts(), 'backend': BACKEND_INSTANCE}
            if route == 'select':
                if set(data) - {'lease', 'epoch', 'login'}:
                    raise ValueError()
                login = data.get('login')
                with _lock:
                    if data.get('lease'):
                        if type(data.get('epoch')) is not int:
                            raise ValueError()
                        lease = _leases.get(data['lease'])
                        if not lease or lease['epoch'] != data.get('epoch'):
                            raise HTTPException(409, 'GitHub account scope changed')
                        lease['home'] = home
                        lease['touched'] = time.monotonic()
                        lease['epoch'] += 1
                    else:
                        for key in list(_leases):
                            if time.monotonic() - _leases[key]['touched'] > TTL:
                                del _leases[key]
                        if len(_leases) >= 512:
                            raise HTTPException(429, 'Too many GitHub clients')
                        key = secrets.token_urlsafe(32)
                        lease = _leases[key] = {'lease': key, 'home': home, 'epoch': 1, 'touched': time.monotonic()}
                    lease['login'] = None
                    expected = lease['epoch']
                if not any(a['login'] == login for a in gh.accounts()):
                    raise backend.AccountError('GitHub account unavailable')
                with _lock:
                    check(lease['lease'], home, expected)
                    lease['login'] = login
                    return {k: lease[k] for k in ('lease', 'epoch', 'login')} | {'backend': BACKEND_INSTANCE}
            if set(data) != {'lease', 'epoch', 'operation'} or type(data['epoch']) is not int:
                raise ValueError()
            args, body = operations.compile_operation(data['operation'])
            with _lock:
                lease = check(data['lease'], home, data['epoch'])
                login = lease['login']
            def dispatch(run):
                # Credential lookup may await slow keyrings/network. Recheck at
                # actual command dispatch, under the same lock as selection.
                with _lock:
                    check(data['lease'], home, data['epoch'])
                    return run()
            result = gh.execute(login, args, body, dispatch=dispatch)
            with _lock:
                check(data['lease'], home, data['epoch'])
            return {'data': redact(result), 'backend': BACKEND_INSTANCE}
    except backend.AccountError as exc:
        raise HTTPException(400, str(exc)) from None
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, 'Unsupported GitHub operation') from None


async def payload(request):
    # Bound streamed bytes, not just a forgeable Content-Length header.
    raw = bytearray()
    async for block in request.stream():
        if len(raw) + len(block) > operations.MAX_BODY:
            raise HTTPException(413, 'GitHub request too large')
        raw.extend(block)
    try:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except ValueError:
        raise HTTPException(400, 'Invalid GitHub request') from None


@router.get('/accounts')
async def accounts(profile: str):
    return await run_in_threadpool(work, profile, {}, 'accounts')


@router.post('/selection')
async def selection(request: Request, profile: str):
    return await run_in_threadpool(work, profile, await payload(request), 'select')


@router.post('/revoke')
async def revoke(request: Request, profile: str):
    return await run_in_threadpool(work, profile, await payload(request), 'revoke')


@router.post('/operation')
async def operation(request: Request, profile: str):
    return await run_in_threadpool(work, profile, await payload(request), 'execute')
