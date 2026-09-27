"""Run from an isolated, built official Hermes checkout; no live app changes."""
import os
import pathlib
import subprocess

root = pathlib.Path.cwd()
if not os.environ.get('GITHERMES_SOURCE') or not os.environ.get('TMPDIR'):
    raise SystemExit('Set GITHERMES_SOURCE and a scratch TMPDIR')
read, write = os.pipe()
xvfb = subprocess.Popen(
    ['Xvfb', '-displayfd', str(write), '-screen', '0', '1600x1000x24', '-nolisten', 'tcp'],
    pass_fds=(write,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
os.close(write)
try:
    with os.fdopen(read) as pipe:
        display = pipe.readline().strip()
    if not display:
        raise RuntimeError('Xvfb did not publish a display')
    env = dict(os.environ, DISPLAY=':' + display)
    with (root / 'stock-smoke.log').open('w') as log:
        result = subprocess.run(
            ['node', '../../node_modules/@playwright/test/cli.js', 'test', '--config', 'stock-pane-smoke.config.ts'],
            cwd=root / 'apps/desktop', env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180,
        )
    print('Playwright exit:', result.returncode)
    raise SystemExit(result.returncode)
finally:
    xvfb.terminate()
    xvfb.wait(timeout=10)
