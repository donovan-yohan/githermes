# Scoped GitHub accounts

## Runtime contract

The trusted unified plugin mounts `dashboard/plugin_api.py` via the existing
Hermes dashboard loader at `/api/plugins/githermes`. Existing session-token/OAuth
middleware and runtime plugin-enable gates remain in force. No plugin-specific
core routing patch or SDK affinity contract is required. GET and POST may land
in different primary/profile backend processes **on the same gateway root**.

The renderer shows login labels only; it persists only the selected login under
connection + profile. It never invokes `gh auth switch`. Separate desktop
clients use independent random capabilities, not a global selected account.
Local git and Hermes session operations remain separate from GitHub REST.

## Process-independent authority

`dashboard/authority.py` uses `<get_default_hermes_root()>/githermes-authority/`:

- Directory mode 0700; lock/database mode 0600, owned by the gateway OS user.
  Unsafe modes, symlinks, storage errors and lock timeouts fail closed. No
  permissions are widened and no profile secrets or tokens enter this store.
- SQLite stores an authority ID and bounded lease metadata (capability, canonical
  profile home, login, epoch, timestamp). The authority ID survives process
  restart, so separate processes do not look like separate account authorities.
- A POSIX `flock` on a permanent `fence.lock` serializes selection, revocation,
  cleanup, and final command dispatch across threads **and processes**. SQLite
  alone is not the dispatch fence. Never unlink or replace the live lock/store.
- Private token lookup and `/user` identity verification happen outside the
  fence. The epoch/profile is rechecked under the fence immediately before
  dispatch. A delayed old-account operation cannot dispatch after a newer
  selection or revocation has completed.
- The fence is held through the operation subprocess, not just its spawn.
  Consequently selection/revocation waits for already-dispatched work. This
  conservatively serializes operations across all clients of the root; it is a
  correctness/throughput tradeoff. Lock waits are bounded to 55 seconds and
  each `gh` subprocess to 45 seconds. A busy response is uncertainty, not an
  authoritative revocation. An already-dispatched mutation is not canceled.
- The `gh` subprocess inherits the lock descriptor. The backend closes its fd
  rather than explicitly unlocking it. If the backend crashes, the inherited
  descriptor retains the fence until `gh` exits; a concurrent switch cannot
  overtake that child. If a crashed backend leaves a hung child, other requests
  time out closed until the child exits/is terminated. There is no mutation
  replay or exactly-once guarantee: after a lost reply, inspect remote state.

The store is shared at the **gateway root**, not a selected profile or plugin
installation directory. All participating processes must share that root,
filesystem and OS user. Local POSIX filesystems with reliable flock/SQLite
semantics are supported; Windows backends, NFS/distributed replicas, differing
roots, and mixed old/new plugin versions are not supported. Windows desktop
clients may connect to a supported remote gateway. Do not delete the store or
restore old database snapshots while requests/children are live.

## Expiry, recovery, and client lifetime

Leases have a one-hour idle TTL and a 512-entry bound. New lease/revocation
creation removes expired rows under the fence; this is bounded lazy cleanup,
not a background service. Revoked entries remain tombstones until expiry.
Random initial epochs prevent a deleted/recreated capability from accepting an
old epoch. Metadata survives backend restart; credentials are resolved fresh.

The renderer allocates a random capability **before** its first selection and
serializes selection/revocation/discovery per connection, across profile changes.
A late A response cannot overwrite a newer B authority. A stale successful
selection is revoked before queued same-connection work proceeds. Even a lost
first response can be revoked using its preallocated capability. Unknown or
expired capabilities receive an authoritative successful revoke with a new
tombstone epoch, permitting Refresh accounts to rediscover/reselect. A timeout,
network failure, 409 or generic error is never interpreted as proof of revocation.
The capability is retained and the UI stays disabled until a successful refresh.

A disconnected/different gateway cannot be addressed through the current generic
SDK. Its capability is retained in renderer memory and revoked upon return;
otherwise it expires. Renderer destruction also leaves bounded TTL cleanup, not
persistent browser capabilities. No cross-gateway revocation claim is made.

Query keys include connection/profile, login, local generation, epoch and lease.
Synchronous profile/gateway transitions invalidate captured reads, mutations and
confirmations. Old results and previous-account placeholders are rejected.

## Profile-bound credentials and security

Every route requires an explicit valid profile and enters Hermes' existing
profile scope. `GH_CONFIG_DIR` is read from `build_profile_secret_scope` for that
canonical profile, **not** ambient process env, even when the process itself was
launched for that profile. Thus primary and profile-process routing resolve the
same configured credential source. Missing/non-absolute configuration fails
closed. Supply it in each profile's `.env`/supported profile secret source;
process-only injection is intentionally insufficient. `HOME` is that profile's
Hermes home. Shared authenticated gh directories are permitted if intentional.

`AccountExecutor` performs private `gh auth token --hostname github.com --user`
and validates `/user` before every operation. Tokens exist only in private
Python memory and fresh child environments, never argv, storage, responses,
prompts or logs. Ambient tokens/debug/proxy variables are not forwarded.
Selected-token echoes and host-recognized sensitive strings are redacted.

Named operations compile to bounded argv; callers cannot supply shell commands,
argv, headers, hosts, templates, file inputs, jq or extensions. JSON bodies use
stdin. GraphQL accepts queries, not mutations. Requests are bounded to 512 KiB;
stdout/stderr each to 4 MiB. Child error output is never forwarded. No shell
sanitizer bypass or permission broadening is used.

## Installation requirements (not performed by this change)

1. Install the unified trusted user plugin, both `dashboard/` and `desktop/`,
   in the participating backends and enable `githermes` with existing Hermes
   plugin controls. A project-directory or desktop-only copy cannot mount the
   Python router. Keep all participating backend plugin versions consistent.
2. Configure an absolute profile-bound `GH_CONFIG_DIR`; `gh` must support
   `auth status --json hosts` and `auth token --user`.
3. Use a POSIX backend and a shared writable gateway-root authority directory.
   Normal backend/plugin loading is needed to mount new Python routes; no
   GitHermes-specific core patch, rebuild or route allowlist is required.

Pane-close persistence is a separate generic `closeBehavior: 'hide'` host feature
covered in native-desktop-integration.md, not an account-routing dependency.

## Verification

Using existing dependencies (bootstrap creates only ignored local test stubs):

```sh
npm run bootstrap
HERMES_QUERY_ROOT=/path/to/existing/hermes-dependencies npm test
HERMES_SOURCE_DIR=/path/to/hermes-source \
/path/to/hermes-python -m pytest test/test_account_backend.py test/test_shared_authority.py -q
```

Python tests mount the actual Hermes router/auth middleware with fake-gh
subprocesses. Two real HTTP backend processes use different process homes and a
shared gateway root; tests cover selection/discovery/operation/revoke, profile
credential poisoning, independent clients and delayed identity verification.
The Node renderer probe connects to those HTTP servers, delays A's selection
reply across a B transition, then proves an old alpha mutation is rejected after
a beta selection. Other tests cover restart, expiry, unknown revoke tombstones,
network uncertainty, lost replies, Unicode, redaction and injection rejection.

No real services, installs, credentials or live GitHub writes are used by these
tests. An installed visual desktop smoke test is not claimed.
