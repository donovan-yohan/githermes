# Official Desktop pane compatibility

## Sources inspected

- Latest `NousResearch/hermes-agent` `main`, freshly fetched for this review: **`ca16be564d0a95f86bd6da44bb41d39cde9db089`**.
- Official source matching the reported `0.21.5+2271` distance: **`ec243785e41e7a12d47b099d9f747c781687f57a`**, annotated tag `rc.14-v0.21.5`.
- `git rev-list --count v2026.9.24..rc.14-v0.21.5` returns **2271**; the base release declares `0.21.5`. The RC tag metadata records `autopublish:false`.

This identifies a matching official source revision, not the installed Windows executable. No Windows build/install stamp was supplied; no Windows execution is claimed. Fork commits are not evidence of official features.

## Public SDK boundary (both revisions)

Paths are relative to `apps/desktop/src`.

| Source | Finding |
|---|---|
| `sdk/index.ts`, `host.revealPane` | Explicitly adopts/reveals the pane, restores its side and fronts its tab. |
| `sdk/index.ts`, `host.paneVisibility` | Readonly atom over the native tree's visibility calculation. |
| `contrib/plugin.ts`, `ctx.register` / `ctx.onDispose` | Public registration returns a disposer removing just that contribution. |
| `components/pane-shell/tree/store.ts`, `closeTreePane` | Native Close disables a sole-pane plugin. No `closeBehavior:'hide'` support. |
| `sdk/index.ts` / `sdk/settings.ts` | No `host.togglePane`, `host.actions`, `host.commands`, generic command executor, or exposed collapsed-side setting. Palette/keybind exports register contributions; they do not invoke host commands. |
| `components/pane-shell/tree/store.ts`, `isPaneVisible` | Checks dismissal, hidden panes, group minimization and active tab, **not collapsed sides or registration membership**. |
| `components/pane-shell/tree/renderer/tree-group.tsx` | `uncloseable:true` removes native Close and also prevents group minimization. |

A true native side-tab X that hides without disabling is not available through these public SDKs. `host.openWorkspace` is a main-workspace tile API, not an equivalent Files-side pane. No private imports, host patches, dummy panes, DOM visibility probes, synthesized keypresses or Settings enablement writes are used by the plugin.

## Delivered plugin-only behavior

- The top-right GitHub button closes a visible pane through its contribution disposer. The next press registers the **same** `githermes:pane` ID and calls `host.revealPane`.
- When Files is the active tab, the first press fronts GitHub; the next closes it.
- The pane's own **Close** button uses the same disposer. It works even when the native tab strip is hidden.
- Navigation, page, palette and status-bar contributions remain registered. Closing never disables the plugin.
- Closed state persists in plugin-owned storage across reloads. Explicit Settings disable still unloads the plugin normally.
- The pane keeps right placement and the non-enforced Files-center dock hint. There is no automatic layout reset or enforced migration.

### Explicit tradeoffs

The pane is `uncloseable:true`: native tab X, middle-click and bulk-close participation are unavailable; a containing group cannot be minimized through its native affordance. This is **not** native-X parity.

**External sidebar collapse remains a host visibility limitation.** If GitHub was active when its whole side was collapsed, the SDK still reports it visible. The first GitHub-button press unregisters that hidden pane; the second reopens the side and pane. The palette's **Open GitHub pane** restores it in one action. Both behaviors were checked against the real SDK; the two-press limitation was reproduced in Electron on both official revisions. No public collapsed-side read/action was found to fix this without violating the plugin-only/no-hacks boundary.

## Verification

- Original `f601735d37af26c27de3d1a2d920b09ccf8b526e` fails the targeted titlebar-close regression (`visible pane must close`, actual `true`, expected `false`); this implementation passes.
- Plugin Node suite: **136 passed, 0 failed, 0 skipped**. SDK/React contract tests use test-only stubs; real QueryObserver tests use the freshly installed official dependency tree.
- Full official SDK + actual plugin module + mounted native `TreeGroup`: **2 Vitest/jsdom tests per revision**, both passing. No extracted SDK method bodies or SDK mocks in these runs.
- Isolated **Linux Electron 40.10.2**: **1 smoke per revision**, both passing, with **zero captured page errors**. Each host was built from its unmodified official source and lockfile, not fork dependencies or patched bundles.
- Actual disk-plugin loader, SDK, renderer and isolated Hermes backend exercised: open → close → reopen → close; in-pane Close → icon reopen; persistent nav; unchanged plugin decisions; Files/GitHub native grouping; Files content survives close; close/reload/reopen; default group retained. The external-collapse limitation is asserted separately, not counted as native toggle parity.
- `node --check desktop/plugin.js` and `git diff --check` pass.

Account transport is intentionally outside this pane-only smoke: the desktop half is staged alone in an isolated test home, so it displays a backend `Plugin not found` status. No account success, live GitHub data, credentials, inference, Windows compatibility or complete light/dark/drag-and-drop parity is claimed. No live installation, publication or merge occurred.

## Reproduction and evidence

See [QA instructions](../qa/NATIVE-PANES.md). Source-bound result summaries are in `qa/pane-verification.json`.

Local isolated hosts and their `stock-pane-evidence/` screenshots, `result.json`, `storage.json`, and `pageerrors.json`:

- `/home/donovanyohan/.hermes/profiles/ebi/cache/scratch/githermes-official-latest`
- `/home/donovanyohan/.hermes/profiles/ebi/cache/scratch/githermes-official-stock`

Each also retains `desktop-build.log`, `stock-native-tests.log`, and `stock-smoke.log`. The scratch builds are verification artifacts only; users do not need a custom Desktop build for this plugin change.
