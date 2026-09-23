"""Subprocess isolation tests; all credentials and GitHub responses are fake."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
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
    print(json.dumps({'login': token.removeprefix('fake-private-')}))
'''


class AccountBackendTests(unittest.TestCase):
    def test_subprocess_account_roundtrip_never_changes_parent_or_config(self):
        source = ROOT / 'dashboard' / 'account_backend.py'
        self.assertTrue(source.exists(), 'missing private per-command account executor')
        spec = importlib.util.spec_from_file_location('account_backend', source)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh = root / 'gh'
            gh.write_text(FAKE_GH)
            gh.chmod(0o700)
            config = root / 'config'
            config.mkdir()
            sentinel = config / 'hosts.yml'
            sentinel.write_text('fake untouched config')
            before = dict(os.environ)
            executor = module.AccountExecutor(str(gh), str(config))
            self.assertEqual([a['login'] for a in executor.accounts()], ['alpha', 'beta'])
            for login in ['alpha', 'beta', 'alpha']:
                result = executor.execute(login, ['api', 'user'])
                self.assertEqual(json.loads(result['stdout'])['login'], login)
                self.assertNotIn('fake-private-', json.dumps(result))
            self.assertEqual(dict(os.environ), before)
            self.assertEqual(sentinel.read_text(), 'fake untouched config')
            # A malicious diagnostic from a child is never passed through.
            gh.write_text(FAKE_GH.replace(
                "print(json.dumps({'login': token.removeprefix('fake-private-')}))",
                "print(json.dumps({'login': token.removeprefix('fake-private-')})) if args[-1] == 'user' else (print(token), print(token, file=sys.stderr))"))
            leaked = executor.execute('alpha', ['repo', 'list'])
            self.assertNotIn('fake-private-', json.dumps(leaked))
            # Credential lookup returning another user's token fails before
            # the requested operation; it never falls back to the active user.
            gh.write_text(FAKE_GH.replace("'fake-private-' + args[args.index('--user')+1]", "'fake-private-beta'"))
            with self.assertRaises(module.AccountError):
                executor.execute('alpha', ['repo', 'list'])
            gh.write_text(FAKE_GH)
            with self.assertRaises(module.AccountError):
                executor.execute('missing', ['api', 'user'])
            for args in [
                ['auth', 'token'], ['auth', 'switch'],
                ['api', 'https://evil.example/'], ['api', 'user', '--verbose'],
                ['api', 'user', '--hostname', 'evil.example'],
                ['api', 'user', '--input', '/some/file'],
                ['api', 'user', '-F', 'body=@/some/file'],
                ['pr', 'view', 'https://evil.example/a/b/pull/1'],
                ['extension', 'exec', 'anything'],
            ]:
                with self.subTest(args=args), self.assertRaises(module.AccountError):
                    executor.execute('alpha', args)


if __name__ == '__main__':
    unittest.main()
