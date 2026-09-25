# Native Desktop backend: no browser UI required

`ctx.rest` reaches Hermes' authenticated `/api/plugins/githermes/*` API through
Desktop IPC. Both `hermes serve` and `hermes dashboard` load the Python router
from `dashboard/manifest.json` before installing the SPA catch-all. The directory
name is a packaging convention, not a requirement to run the browser dashboard.

## Distinguish the failures

- **404 with “Headless backend ... web UI disabled”**: the request reached the
  headless catch-all, not GitHermes. Its route was not registered in that process.
  Check the actual connection/backend launch home, complete installed package,
  startup import log, and startup time relative to installation. The message does
  not mean the API needs a web UI.
- **404 “Plugin not found”**: the host's runtime enable/disable gate rejected the
  request. The Desktop UI toggle is separate from backend `plugins.enabled`.
- **500 on an older host with `No module named hermes_cli.web_server_profiles`**:
  GitHermes previously imported only the host's newer split module. The scope
  helper now falls back to the older `hermes_cli.web_server` location, without
  swallowing missing dependencies inside the newer module.

Backend discovery scans the process launch home's `plugins/` and the default
root's `plugins/`, preferring the launch-local package. It does not scan every
sibling profile. Desktop's renderer materialization can scan **all** local
profiles and publish a package's `desktop/` half into the app-level directory.
Consequently a visible GitHub pane is not proof that the backend serving its
requests discovered the Python half. Passing `?profile=...` scopes execution;
it does not import a package from that profile into another process.

A complete trusted package, enabled for the serving backend at startup, is
required. Copying only `desktop/plugin.js`, enabling only the UI, or installing
under another profile cannot establish backend registration. Do not start the
browser dashboard to work around a missing route. Route loading is startup-only
on the host revisions tested here; this change does not add hot-loading or alter
plugin trust/enable policy.

## Real CLI verification

Run with the Python environment containing the selected host's dependencies:

```sh
HERMES_SOURCE_DIR=/path/to/hermes /path/to/host/.venv/bin/python \
  -m pytest test/test_cli_backend.py -q
```

The tests launch the real `hermes_cli.main` CLI for `serve` and `dashboard`, use
isolated homes/configuration, discover the real manifest, and make loopback HTTP
requests. No `TestClient`, router injection, discovery mocks, real GitHub auth,
or real GitHub mutations are involved. A synthetic `gh` executable records its
calls; profile A→B→A execution verifies private child credential environments.
The dashboard case uses a minimal test HTML fixture, not a production UI build.
The headless case leaves that same fixture on disk and proves it is not served.

The runner avoids editable-install `.pth` import finders so a dependency venv
from a newer checkout cannot silently provide modules absent in the selected
older host checkout.

Verified host source layouts:

- Fork main `11ad8ebe6fcc911674a7853263cadc85f1f2f537`: monolithic scope helper
  (`hermes_cli.__version__` is `0.20.4`). The unpatched plugin fails account HTTP
  requests with 500; the compatibility fallback fixes that request path.
- Current source `da77a7e2e876ec3a9b882fa0a84085373f9ae097`: split scope helper.

These are backend compatibility checks, not a blanket reduction of the unified
package's declared `requires_hermes >=0.21.1` or proof of every Desktop UI feature
on older releases. No host loader change, credential fallback, token access in
the renderer, or global `gh auth switch` is introduced.
