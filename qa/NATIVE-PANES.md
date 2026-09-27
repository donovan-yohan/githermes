# Public-SDK pane verification

This branch needs no host patches. See [official compatibility and limitations](../docs/stock-2271-compatibility.md).

## Plugin checks

```sh
npm run bootstrap
HERMES_QUERY_ROOT=/path/to/dependency-installed-official-hermes node --test
node --check desktop/plugin.js
git diff --check
```

The bootstrap writes test-only SDK/React stubs in this plugin worktree. Never run it against a host dependency directory.

## Official SDK and Electron checks

Use an isolated checkout of an official commit, not the live app or a fork. Both these revisions were exercised:

- `ca16be564d0a95f86bd6da44bb41d39cde9db089` — freshly fetched upstream main.
- `ec243785e41e7a12d47b099d9f747c781687f57a` — `rc.14-v0.21.5`, matching the `+2271` source distance.

From the isolated official checkout root:

```sh
npx --yes npm@11.17.0 ci --no-audit --no-fund
uv sync --python 3.14
npm run build --workspace apps/desktop
export GITHERMES_SOURCE=/absolute/path/to/githermes-worktree
cp "$GITHERMES_SOURCE/qa/upstream-pane.vitest.ts" upstream-pane.test.ts
node node_modules/vitest/vitest.mjs run --config "$GITHERMES_SOURCE/qa/upstream-pane.config.mjs"
cp "$GITHERMES_SOURCE/qa/stock-pane-smoke.ts" apps/desktop/
cp "$GITHERMES_SOURCE/qa/stock-pane-smoke.config.ts" apps/desktop/
python3 "$GITHERMES_SOURCE/qa/run-stock-smoke.py"
```

Install the **whole** upstream workspace lockfile: a desktop-only install omitted `lucide-react`, imported by an official onboarding component. No manifest changes were needed. `desktop` is not a Python extra; the current official runtime dependencies require Python 3.14.

The runner uses Xvfb's display-fd handshake (no `xauth` required), writes `stock-smoke.log`, and closes its display. `TMPDIR` must point to an isolated scratch directory. The upstream fixture creates isolated HOME, Hermes home, Electron user data, and a seeded synthetic session. Test setup additionally isolates GitHub config and disables login-shell probing. It uses a dead inference endpoint and stages only the desktop plugin: expected missing-account-backend status is **not** an account regression investigation.

The smoke uses actual mouse/keyboard controls, not private renderer mutation. It asserts navigation via the sidebar list item, not the similarly named titlebar icon. Files' lone Auto strip disappears after GitHub closes; verify Files **content**, not a nonexistent strip. The native sidebar toggle may first restore a minimized Terminal sibling before its next press collapses the side.

Assertions cover the requested lifecycle, plugin decision storage, Files grouping and reload. A separate characterization verifies the remaining external-collapse two-press limitation. Real SDK tests assert that public explicit Open restores the collapsed side and that no `host.actions`/`host.commands` escape hatch exists.

Results are captured in `stock-pane-evidence/`: screenshots at each checkpoint, final DOM, persisted storage, platform/source SHA, and page errors. `qa/pane-verification.json` records the completed official runs and tested plugin digest. No Windows claim.

`qa/pane-smoke.ts` / `qa/pane-smoke.config.ts` are historical fork-host tests from the base commit, **not** the checks or prerequisites for this implementation.
