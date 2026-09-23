# Native pane integration

## Host requirements

The titlebar uses `host.togglePane('githermes:pane')`. This public SDK action
must delegate to the native tree's `togglePaneVisible`: reveal/front if not
visible, otherwise close using the pane's normal policy. It must not maintain a
second visibility boolean. Older hosts fall back to Open, not a pretend toggle.
Page and palette **Open** continue to call `host.revealPane` and are idempotent.

The desktop also needs `PaneData.closeBehavior: 'hide'` support (companion host
commit `962febc2eb87ce239b38d8e55078115c76434da0`). That opt-in prevents native
Close from disabling this single-pane plugin. It is distinct from toggle API
support. The legacy `hermes:pane-toggle-reveal` event is consumed only by narrow
collapsible overlays; it cannot implement a wide-screen plugin toggle.

`placement: 'right'` alone picks the first right-placement pane, **Review**, in
the host's default tree, not Files. The non-enforced
`dock: { pane: 'files', pos: 'center' }` hint requests native Files tabs on first
adoption. Existing layouts remain authoritative: no reset, migration, or enforced
dock. Native drag/drop remains the way to move an already-placed pane. A lone
pane can have no tab strip in Auto mode; hover its zone and use **Show tabs**
(`Ctrl+Alt+T` on Linux) to expose the native drag handle.

## Reproducible Electron smoke

`qa/pane-smoke.ts` and `qa/pane-smoke.config.ts` are host-harness tests, not Node
unit tests. Copy them into an isolated built host's `apps/desktop/`, alongside its
real `e2e/fixtures.ts`. The existing scratch harness is:

```
/home/donovanyohan/.hermes/profiles/ebi/cache/scratch/githermes-render-check
```

It supplies `fake-gh-inbox.py`, `.venv`, installed Electron/Playwright, and
`rerun.py` (owns Xvfb and closes the isolated app). From that harness:

```
GITHERMES_SOURCE=/home/donovanyohan/githermes-pane-toggle \
  QA_CONFIG=pane-smoke.config.ts python3 rerun.py
```

Build the host with the SDK toggle patch plus the hide-close prerequisite before
running. Do not patch minified bundles or installed dependencies. The test seeds
one synthetic durable session through the real SessionDB so Files has a working
directory, then uses actual renderer controls and mouse pointer drags. It checks:

- titlebar open → hide → reopen, with sidebar navigation still present;
- Files and GitHub share one native tab group on a fresh layout;
- drag GitHub out, reload and retain that custom placement, drag back onto Files;
- clicking the icon when Files is active fronts GitHub before the next click hides;
- native Close preserves navigation, page Open twice and palette Open twice stay open;
- real isolated plugin backend and fake-gh audit, with synthetic inbox rows loaded.

No live install, app restart, auth switching, inference call, or GitHub mutation.
Credentials and homes are isolated; `SHELL=/bin/false` prevents login-shell PATH
restoration from bypassing fake gh. The fake executable never connects to GitHub.

## Verified results

- Plugin Node suite: 129 pass, 2 optional dependency tests skipped, 0 fail.
- Host SDK/native close/visibility tests: 22 pass across 3 files.
- Electron smoke: 1 pass (27.6s test / 28.1s runner).
- The pre-fix native smoke failed because the second titlebar click left the
  account selector visible. The host SDK regression fails without `togglePane`.
- Unmodified host dependencies still emit the previously documented
  `Maximum update depth exceeded / getSnapshot` error (30 occurrences across
  the reload smoke). No diagnostic bundle patch was applied. This is not an
  error-free host renderer claim.

Evidence under the harness `pane-smoke/`: `files-github-tabs.png`,
`dragged-out.png`, `persisted-detached.png`, `dragged-into-files.png`,
`toggled-closed.png`, `open-idempotent.png`, `result.log`, `pageerrors.json`,
`fixture-calls.jsonl`, and `storage.json`. The final audit had 57 fake-gh calls.
