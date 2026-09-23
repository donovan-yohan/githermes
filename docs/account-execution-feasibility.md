# Scoped GitHub accounts: implementation and installation

## Delivered

The unified package now mounts `dashboard/plugin_api.py` through
`dashboard/manifest.json` (`api: plugin_api.py`). Hermes' real dashboard loader
imports its `router` under `/api/plugins/githermes`; the existing session-token /
OAuth authentication and runtime plugin-enable gates protect these routes.
The backend is not an agent tool and never receives renderer shell commands.

The native account Select appears only when metadata contains multiple successful
identities. Selection persists **only the login**, under connection + profile.
A disappeared saved identity fails closed; an explicit `Use LOGIN` control can
select the sole remaining identity. No global `gh auth switch` is performed.

All GitHub data paths now use structured REST operations, including discovery,
manual repository lookup, session PRs, update comparisons, PR/issue details,
checks, comments, review/merge/state writes, and the six-section GraphQL inbox.
Local git, install-ledger and Hermes session/update commands remain separate.
Copying a checkout command does not execute it.

## Backend boundaries

- Every REST route requires an explicit `profile` query parameter and enters
  Hermes `_config_profile_scope(profile)` inside its threadpool worker.
- `get_hermes_home()` and `get_secret('GH_CONFIG_DIR')` resolve **inside** that
  context. Missing/non-absolute `GH_CONFIG_DIR` fails closed. `HOME` is the
  selected Hermes profile home, not ambient process `HOME`.
- A private `gh auth token --hostname github.com --user LOGIN` subprocess resolves
  the credential. `/user` verifies it before each operation. The token exists
  only in private Python memory and that command's fresh child environment;
  it is never placed in argv, HTTP responses, renderer storage, shell RPC,
  prompts or logs. Inherited tokens/debug/proxy settings are not forwarded.
- `operations.py` compiles named operations into argv. No caller-provided argv,
  shell, headers, file inputs, templates, jq, host override or extension is
  accepted. JSON comment/GraphQL bodies use stdin. GraphQL accepts queries,
  not mutations; REST writes are confined to supported comments/reviews.
- GitHub output is parsed as JSON; selected-token echoes are removed and the
  host's `redact_sensitive_text(..., force=True)` recursively redacts plain
  string values/keys before HTTP serialization. There is **no base64 GitHub
  response transport** and no removal/bypass of the shell sanitizer.
- Requests are limited to 512 KiB; stdout and stderr each to 4 MiB with child
  termination at the cap; each subprocess has a 45-second timeout. Error output
  is never forwarded. HTTP calls allow 180 seconds for credential + operation
  subprocesses. `pr checks` preserves valid nonzero-exit JSON, distinguishing
  the CLI's no-checks case from other failures.

## Selection and stale-work fences

Opaque in-memory leases have a one-hour TTL and a bounded client table. Selection
advances a server epoch and invalidates the old login before metadata validation.
The executor verifies the epoch after private identity resolution, under the same
lock as selection, immediately at operation dispatch. An already-dispatched
command is not retroactively canceled; selection waits for it to finish.

The renderer synchronously invalidates on connection/profile/gateway transitions
(including rapid A → B → A before a React effect). Refresh revokes its old lease
before discovery. Query keys include connection/profile, login, local generation,
server epoch and lease. Old results are rejected; previous-account placeholders
are not reused. Repository and inbox subtrees remount on account generations,
resetting old confirmations/composers. Writes capture the rendered scope.

Selection leases are retained by connection in memory, not persisted. Backend
instance IDs fence accidental GET/POST routing to different processes. Backend
restart/expiry or transport failures fail closed; reconnect/reload may be needed
to establish a fresh lease. This is intentionally not silent fallback to another
account. Separate desktop clients have independent selections.

## Required installation (not performed by this change)

1. Install **this unified package** as a trusted user plugin on the connected
   backend, including `dashboard/` and `desktop/`; enable `githermes` in the
   backend's `plugins.enabled` (the CLI command is `hermes plugins enable githermes`).
   A project-directory plugin cannot mount Python code. A desktop-only copy is
   no longer sufficient; remove any obsolete standalone duplicate that shadows
   the unified package.
2. Supply the intended absolute `GH_CONFIG_DIR` in each served profile's scoped
   environment source. A shared authenticated CLI directory is supported. No
   account/credential configuration files are modified by this feature.
   The installed `gh` must support `auth status --json hosts` and
   `auth token --user` (the previously inspected host uses 2.92.0).
3. **Local multi-profile Desktop routing requires the companion**
   [`integration/hermes-profile-routing.patch`](../integration/hermes-profile-routing.patch).
   The current Desktop `localPrimaryRequestScope` does not recognize plugin
   POSTs, and therefore can pool them away from the shared primary used for GETs.
   The patch allowlists only these four explicitly profile-bound GitHermes
   routes; it does not declare arbitrary plugin endpoints safe. Build/deploy the
   matching Desktop host change. The plugin detects a split and stays disabled
   rather than allowing a credential/cache mismatch. A single shared remote
   backend already routes these requests together.
4. Reload/restart the backend after installing/enabling Python routes, then load
   the matching Desktop plugin. No install, restart or live-auth change was done
   during development. Pane-close persistence separately needs the existing
   `closeBehavior: 'hide'` host change described in native-desktop-integration.md.

The independent shell `@_profile_scoped` fix is **not** a prerequisite for these
GitHub operations: the new REST router binds its own profile scope. It remains
valuable for unrelated shell RPC environment behavior.

## Inbox integration seam

`githubOperation({ operation: 'github.api', path: 'graphql', method: 'POST',
body: { query, variables } }, capturedScope)` returns the redacted GraphQL JSON
envelope. `readInboxRequest({ kind: 'graphql', query, variables }, guard)` adapts
that seam. Inbox classification, filters and view contents are unchanged by the
account integration. Context invalidation uses `INBOX_CONTEXT_CHANGED`, preventing
optional team-search error handling from swallowing a stale-account failure.

## Verification

Use already installed dependencies; these commands do not install anything:

```sh
npm run bootstrap
HERMES_SOURCE_DIR=/path/to/hermes-source \
HERMES_QUERY_ROOT=/path/to/existing/hermes-dependencies npm test
HERMES_SOURCE_DIR=/path/to/hermes-source \
/path/to/hermes-python -m pytest test/test_account_backend.py -q
```

`bootstrap` writes only this checkout's ignored SDK/React test stubs. Real polling
uses the supplied QueryClient/QueryObserver package, not those stubs. The host
routing test applies the companion patch to a disposable scratch copy, bundles
actual Desktop routing source, reproduces the original gap, and verifies all four
patched routes plus unchanged unrelated-plugin rejection.

Python tests use real fake-gh subprocesses and Hermes' **actual** FastAPI loader,
auth middleware, runtime disable gate and profile context manager. They cover
A → B → A, profile changes, ambient-env poisoning, stale writes during delayed
identity resolution, preserved Unicode JSON, forced redaction, bounded responses,
and rejected injection shapes. They never request live credentials or contact
GitHub. Node tests exercise the production adapter, selector/refresh/remount
contracts, persisted selection, missing identities, delayed responses, rapid
profile changes, backend-process mismatches and the existing suite.

An installed Desktop visual smoke test and live selected-account GitHub writes
were deliberately not performed. Passing component-contract tests is not a claim
of a mounted visual test. Public GitHub inbox parity gaps remain in pr-inbox.md.
