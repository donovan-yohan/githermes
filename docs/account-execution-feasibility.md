# Account execution feasibility (not a shipped selector)

## Verified

- Installed CLI: `/usr/bin/gh`, version 2.92.0.
- `gh auth token --hostname github.com --user LOGIN` supports private credential
  resolution. `gh api` has no account-selection flag.
- Filtered `gh auth status --json hosts` metadata against the explicit host
  `GH_CONFIG_DIR` identifies `donovan-yohan` (active) and `ebi-kasei` (inactive),
  both successful. No credential file was read by the investigation.
- Official Desktop SDK supports `ctx.rest`, with a Python FastAPI router mounted
  from `dashboard/plugin_api.py` and `dashboard/manifest.json`. This is the
  appropriate transport, not `host.request('shell.exec')` with credential text.
- The backend import requires the gateway-side plugin to be explicitly enabled.
  A desktop-only install cannot provide private execution.

## Artifact delivered

`dashboard/account_backend.py` is an **unmounted private executor foundation**.
It uses an explicit executable and credential configuration directory; a small
child-environment allowlist; metadata-only discovery; private captured token
resolution; `/user` verification before operations; and a fresh token environment
per subprocess. It never invokes `gh auth switch`, writes CLI configuration, or
modifies the parent environment. Unsupported commands, external hosts, file
inputs, verbose output, arbitrary headers and extensions are rejected. Errors
are fixed strings, and the selected token is removed from returned stdout as
additional defense in depth.

`test/test_account_backend.py` exercises real fake-gh subprocesses, A → B → A,
unchanged parent environment and fake config, unknown/mismatched identities,
credential echo suppression, and disallowed argument shapes. It never requests
live tokens. Run with `python3 -m unittest discover -s test -p 'test_account_backend.py' -v`.

## Not implemented; do not install as a completed feature

No router, manifest, desktop selector or transport migration is included. The
existing desktop continues using its pre-existing shell transport. This is not
a complete solution and does not establish end-to-end mutation fencing.

The integration must:

1. Enter the gateway's `_config_profile_scope(profile)` before resolving an
   explicit `GH_CONFIG_DIR` using profile-scoped configuration. Do not inherit
   another profile's config directory or fall back to the process user's
   default. Coordinate with the independently owned core scope fix.
2. Define typed, bounded plugin operations. Do not expose unrestricted argv as
   an HTTP API merely because the private executor has defensive validation.
   Bound request/response sizes and use `agent.redact.redact_sensitive_text`
   with `force=True` at the HTTP boundary; exact-token stripping is not a
   replacement for Hermes redaction.
3. Migrate **all** GitHub reads/writes: `sh`, `shBig`, the independent
   `shJsonLoose`, comment posting (currently temporary files), repository
   discovery/lookup, session PR lookup, update comparisons, PR merge/review,
   and issue state changes. Local git and Hermes operations stay separate.
4. Include connection, profile, login and generation in query scope; persist
   the chosen login by connection/profile. Changing A → B → A must produce a
   new generation, not revive stale A mutations. Carry the captured scope
   through every awaited step, not just check the current scope when executing.
5. Fence mutation dispatch on the backend using an opaque client lease plus
   generation, and reject queued old-generation operations after switching.
   A previously dispatched mutation cannot be canceled retroactively.
6. Render an account control only after discovering more than one available
   identity. Missing selected identities fail closed rather than picking the
   active CLI identity. Use labels and controls only, no helper copy/tooltips.
7. Exercise SDK REST profile/connection routing and delayed-response/mutation
   races in integration tests, then verify in the actual desktop separately.

The supported architecture is feasible; no fundamental SDK blocker was found.
The remaining items are unfinished implementation, not grounds for an insecure
fallback. No live auth mutation, installation, gateway restart, push or merge
was performed. Notification APIs were not developed or modified.
