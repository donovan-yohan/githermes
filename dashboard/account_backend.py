"""Private GitHub subprocess execution. No shell, auth switching, or token responses.

This module deliberately has no HTTP entrypoint: mount only a validated operation API,
not arbitrary argv. The caller must bind a profile's explicit GH_CONFIG_DIR and apply
Hermes output redaction before returning GitHub content to the desktop.
"""
import json
import os
import re
import subprocess


class AccountError(RuntimeError):
    """Safe, fixed-message error: never attach subprocess output or exceptions."""


class AccountExecutor:
    def __init__(self, executable, config_dir):
        if not os.path.isabs(executable) or not os.path.isabs(config_dir):
            raise AccountError('GitHub backend configuration unavailable')
        self.executable = executable
        # Explicit allowlist: no inherited tokens, debug, proxies, GH_HOST, repo,
        # loaders, git tracing, or custom HTTP transports.
        self.env = {k: os.environ[k] for k in (
            'HOME', 'PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'WINDIR',
            'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR',
        ) if k in os.environ}
        self.env.update(GH_CONFIG_DIR=config_dir, GH_HOST='github.com',
                        GH_PROMPT_DISABLED='1', GH_NO_UPDATE_NOTIFIER='1',
                        GH_NO_EXTENSION_UPDATE_NOTIFIER='1', GH_PAGER='cat',
                        GH_TELEMETRY='false', NO_COLOR='1')

    def _run(self, args, env):
        try:
            return subprocess.run([self.executable, *args], env=env,
                                  stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=45, check=False,
                                  cwd=self.env['GH_CONFIG_DIR'])
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise AccountError('GitHub command unavailable') from None

    def accounts(self):
        result = self._run(['auth', 'status', '--hostname', 'github.com', '--json',
                            'hosts', '--jq',
                            '[.hosts["github.com"][] | {login,active,state}]'], self.env)
        try:
            rows = json.loads(result.stdout)
            if not isinstance(rows, list):
                raise ValueError()
            accounts = []
            seen = set()
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

    @staticmethod
    def validate(args):
        if (not isinstance(args, list) or not args or len(args) > 80
                or any(not isinstance(a, str) or '\x00' in a for a in args)):
            raise AccountError('Unsupported GitHub operation')
        if args[0] == 'api':
            tail = args[1:]
        elif len(args) >= 2 and tuple(args[:2]) in {
            ('repo', 'list'), ('repo', 'view'), ('pr', 'list'), ('pr', 'view'),
            ('pr', 'checks'), ('pr', 'merge'), ('pr', 'review'),
            ('issue', 'list'), ('issue', 'view'), ('issue', 'close'), ('issue', 'reopen'),
        }:
            tail = args[2:]
        else:
            raise AccountError('Unsupported GitHub operation')
        values = {'--hostname', '--repo', '--json', '--jq', '--method', '-X',
                  '--limit', '--state', '--head', '--search', '-f', '--raw-field'}
        toggles = {'--silent', '--include', '--approve', '--merge', '--squash',
                   '--rebase', '--delete-branch'}
        positional = []
        index = 0
        while index < len(tail):
            arg = tail[index]
            if arg in values:
                index += 1
                if index == len(tail):
                    raise AccountError('Unsupported GitHub operation')
                value = tail[index]
                if arg == '--hostname' and value != 'github.com':
                    raise AccountError('Unsupported GitHub host')
                if arg == '--repo' and not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', value):
                    raise AccountError('Unsupported GitHub repository')
                if arg in {'--method', '-X'} and value not in {'GET', 'POST', 'PATCH', 'PUT', 'DELETE'}:
                    raise AccountError('Unsupported GitHub method')
            elif arg in toggles:
                pass
            elif arg.startswith('-'):
                raise AccountError('Unsupported GitHub option')
            else:
                positional.append(arg)
            index += 1
        if args[0] == 'api':
            if len(positional) != 1 or not re.fullmatch(
                r'(?:user|search/issues|repos/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_./?=&%,-]+)',
                positional[0],
            ) or '..' in positional[0] or '%' in positional[0]:
                raise AccountError('Unsupported GitHub endpoint')
        elif len(positional) > 1 or any(not re.fullmatch(r'[A-Za-z0-9_./-]+', p) for p in positional):
            raise AccountError('Unsupported GitHub argument')

    def execute(self, login, args):
        self.validate(args)
        if not any(row['login'] == login for row in self.accounts()):
            raise AccountError('GitHub account unavailable')
        result = self._run(['auth', 'token', '--hostname', 'github.com', '--user', login], self.env)
        token = result.stdout.strip()
        if result.returncode or not token or any(c.isspace() for c in token):
            raise AccountError('GitHub account unavailable')
        env = dict(self.env, GH_TOKEN=token)
        # Resolve /user with the selected credential before any mutation. Never
        # substitute the active account if the selected credential is stale.
        identity = self._run(['api', '--hostname', 'github.com', 'user'], env)
        try:
            verified = json.loads(identity.stdout).get('login') == login
        except (ValueError, AttributeError):
            verified = False
        if identity.returncode or not verified:
            raise AccountError('GitHub account unavailable')
        result = self._run(args, env)
        # Error diagnostics can echo request headers; expose a fixed message.
        # Exact-token stripping is defense in depth, not a replacement for the
        # host's general secret redaction at the eventual HTTP boundary.
        return {'code': result.returncode,
                'stdout': result.stdout.replace(token, '[REDACTED]'),
                'stderr': 'GitHub command failed' if result.returncode else ''}
