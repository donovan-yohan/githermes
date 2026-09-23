"""Private, bounded GitHub subprocess execution. No global auth changes."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_OUTPUT = 4 * 1024 * 1024
COMMAND_TIMEOUT = 45


class AccountError(RuntimeError):
    """Fixed safe messages only; never attach child output or exceptions."""


class AccountExecutor:
    def __init__(self, executable, config_dir, home=None):
        home = home or config_dir
        if not all(os.path.isabs(p) for p in (executable, config_dir, home)):
            raise AccountError('GitHub backend configuration unavailable')
        self.executable = executable
        self.fence_fd = None
        self.env = {k: os.environ[k] for k in (
            'PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'WINDIR',
            'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR',
        ) if k in os.environ}
        self.env.update(HOME=home, GH_CONFIG_DIR=config_dir, GH_HOST='github.com',
                        GH_PROMPT_DISABLED='1', GH_NO_UPDATE_NOTIFIER='1',
                        GH_NO_EXTENSION_UPDATE_NOTIFIER='1', GH_PAGER='cat',
                        GH_TELEMETRY='false', NO_COLOR='1')

    def _run(self, args, env, body=None):
        # A fresh, session-independent interpreter owns the deadline and fence.
        # Credentials/body travel only through a private pipe, never argv/files.
        request = dict(executable=self.executable, args=args, env=env, body=body,
                       timeout=COMMAND_TIMEOUT, limit=MAX_OUTPUT, fence=self.fence_fd)
        try:
            with subprocess.Popen(
                    [sys.executable, '-I', str(Path(__file__).with_name('command_supervisor.py'))],
                    env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, start_new_session=True,
                    pass_fds=() if self.fence_fd is None else (self.fence_fd,)) as proc:
                output, _ = proc.communicate(json.dumps(request).encode())
            if proc.returncode:
                raise AccountError('GitHub command unavailable')
            result = json.loads(output)
            if result.get('error'):
                messages = {'timeout': 'GitHub command timed out',
                            'overflow': 'GitHub response too large'}
                raise AccountError(messages.get(result['error'], 'GitHub command unavailable'))
            return subprocess.CompletedProcess(args, result['code'],
                                               result['stdout'], result['stderr'])
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, KeyError):
            raise AccountError('GitHub command unavailable') from None

    def accounts(self):
        result = self._run(['auth', 'status', '--hostname', 'github.com', '--json',
                            'hosts', '--jq',
                            '[.hosts["github.com"][] | {login,active,state}]'], self.env)
        try:
            rows = json.loads(result.stdout)
            if not isinstance(rows, list):
                raise ValueError()
            accounts, seen = [], set()
            for row in rows:
                login = row.get('login')
                if (row.get('state') == 'success' and isinstance(login, str)
                        and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', login)
                        and login.lower() not in seen):
                    seen.add(login.lower())
                    accounts.append({'login': login, 'active': row.get('active') is True,
                                     'state': 'success'})
            return accounts
        except (ValueError, AttributeError, TypeError):
            raise AccountError('GitHub accounts unavailable') from None

    def execute(self, login, args, body=None, dispatch=None):
        # args is private compiler output, NEVER an HTTP request field.
        if not any(row['login'] == login for row in self.accounts()):
            raise AccountError('GitHub account unavailable')
        result = self._run(['auth', 'token', '--hostname', 'github.com', '--user', login], self.env)
        token = result.stdout.strip()
        if result.returncode or not token or any(c.isspace() for c in token):
            raise AccountError('GitHub account unavailable')
        env = dict(self.env, GH_TOKEN=token)
        identity = self._run(['api', '--hostname', 'github.com', 'user'], env)
        try:
            verified = json.loads(identity.stdout).get('login') == login
        except (ValueError, AttributeError):
            verified = False
        if identity.returncode or not verified:
            raise AccountError('GitHub account unavailable')
        run = lambda: self._run(args, env, body)
        result = dispatch(run) if dispatch else run()
        # pr checks uses nonzero exit for pending/failing checks, still with JSON.
        if result.returncode and args[:2] != ['pr', 'checks']:
            raise AccountError('GitHub command failed')
        raw = result.stdout.replace(token, '[REDACTED]')
        if result.returncode and args[:2] == ['pr', 'checks'] and not raw.strip():
            if 'no checks reported' in result.stderr.lower():
                return []
            raise AccountError('GitHub command failed')
        try:
            return json.loads(raw) if raw.strip() else None
        except ValueError:
            # Mutation human-readable success output is not data and can echo
            # credentials. It is deliberately discarded, not sent to the UI.
            if args[:2] in (['pr', 'merge'], ['pr', 'review'], ['issue', 'close'], ['issue', 'reopen']):
                return None
            raise AccountError('Invalid GitHub response') from None
