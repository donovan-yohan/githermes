"""Mounted by Hermes' authenticated /api/plugins/githermes router loader."""
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3

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
authority = sibling('authority')


def scope(profile):
    from hermes_cli.web_server_profiles import _config_profile_scope
    return _config_profile_scope(profile)


def executor():
    from hermes_constants import get_hermes_home
    from agent.secret_scope import build_profile_secret_scope
    # Resolve AFTER request scope entry; never use process GH_CONFIG_DIR/HOME.
    home = str(get_hermes_home().resolve())
    config = build_profile_secret_scope(Path(home)).get('GH_CONFIG_DIR')
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


def work(profile, data, route):
    if not isinstance(profile, str) or not profile.strip() or profile == 'current':
        raise HTTPException(400, 'Explicit GitHub profile required')
    try:
        with scope(profile):
            if route == 'revoke':
                if set(data) != {'lease', 'epoch'} or type(data.get('epoch')) is not int:
                    raise ValueError()
                with authority.locked() as store:
                    return store.revoke(data['lease'])
            home, gh = executor()
            if route == 'accounts':
                accounts = gh.accounts()
                with authority.locked() as store:
                    return {'accounts': accounts, 'backend': store.backend}
            if route == 'select':
                if set(data) - {'lease', 'epoch', 'login'} or ('lease' in data and type(data.get('epoch')) is not int):
                    raise ValueError()
                with authority.locked() as store:
                    reserved = store.select(data, home)
                if not any(a['login'] == data.get('login') for a in gh.accounts()):
                    raise backend.AccountError('GitHub account unavailable')
                with authority.locked() as store:
                    return store.complete(reserved, data['login'])
            if set(data) != {'lease', 'epoch', 'operation'} or type(data['epoch']) is not int:
                raise ValueError()
            args, body = operations.compile_operation(data['operation'])
            with authority.locked() as store:
                lease = store.check(data['lease'], home, data['epoch'])
                login, instance = lease['login'], store.backend
            def dispatch(run):
                # The OS lock fences all processes, not only this worker. gh
                # inherits its fd, so killing this backend cannot release the
                # fence while its already-dispatched gh child is still alive.
                with authority.locked() as store:
                    store.check(data['lease'], home, data['epoch'])
                    gh.fence_fd = store.fd
                    try:
                        return run()
                    finally:
                        gh.fence_fd = None
            result = gh.execute(login, args, body, dispatch=dispatch)
            with authority.locked() as store:
                store.check(data['lease'], home, data['epoch'])
            return {'data': redact(result), 'backend': instance}
    except backend.AccountError as exc:
        raise HTTPException(400, str(exc)) from None
    except (OSError, sqlite3.Error):
        raise HTTPException(503, 'GitHub authority unavailable') from None
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
