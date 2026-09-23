# Pull request inbox

GitHermes Inbox represents [github.com/pulls/inbox](https://github.com/pulls/inbox), not the notifications inbox. It uses read-only GraphQL PR search and exposes six collapsible sections:

| Section | Public-API rule implemented here |
| --- | --- |
| Needs your review | `user-review-requested:@me` |
| Needs your teams review | `team-review-requested-user:@me` |
| Needs action | Authored or assigned, non-draft, with changes requested, conflicting mergeability, or failure/error in the current head commit check rollup |
| Ready to merge | Authored or assigned, explicitly non-draft and open, `MERGEABLE`, `CLEAN`, review approved or null, and current head check rollup SUCCESS or explicitly absent |
| Your drafts | Open draft PRs returned by `author:@me` |
| Waiting for review | Authored or assigned, non-draft, not action/ready, with review required or outstanding review requests |

The current public API describes CLEAN as “Mergeable and passing commit status.” We use that positive GitHub merge-state verdict together with review decision and the current head's check rollup. We do not invent a verdict from missing fields or unknown mergeability. We do not independently reconstruct required-check/ruleset configuration, and a READY row is not authorization to merge. UNKNOWN, BLOCKED, BEHIND, UNSTABLE and HAS_HOOKS are not promoted to ready. Optional failing checks can conservatively put a PR in Needs action. These rules are a documented approximation, **not a claim of exact GitHub-internal classification parity**.

## Views and scope

Authored by me, Assigned to me, Involves me and Review requested are available. Review requested unions the explicit personal and team sources. A PR requested of both a person and a team can appear in both sections. Authored/assigned status buckets use precedence draft → action → ready → waiting. PRs without sufficient classification evidence remain visible below the six sections, with an `Unclassified PRs` status rather than disappearing or pretending to be ready.

Repo/multi-repo (maximum five), organization and update-recency filters are applied in each server-side search. Repository and organization restrictions intersect; a disjoint selection sends no request. Results are newest-updated first, deduplicated by GraphQL ID, and bounded to three pages of 50 for each source. Counts describe loaded unique PRs, not sums of overlapping search totals. `Partial results` marks a page cap or truncated review request connection.

The team qualifier is explicitly documented by GitHub and resolves membership server-side. We do not infer teams from mentions, notification reasons or personal review search. If team search fails/returns GraphQL errors, `Team reviews unavailable · Partial results` is shown. Membership and repository visibility remain limited to what the authenticated GitHub account/API can see; success is not proof of visibility into hidden/SSO-restricted resources. A denied primary query fails visibly instead of claiming an empty inbox.

## Transport seam

`loadGitHubInbox(filters, read, now)` accepts an injectable async transport. Each call receives `{ kind: 'graphql', query: INBOX_GRAPHQL, variables: { search, cursor } }` and expects the unmodified GraphQL JSON envelope. `GitHubInbox({ read })` and `inboxQueryOptions(..., read)` use the same seam. The default adapter uses the existing guarded `shJsonBig` transport without bypassing secret redaction. A selected-account backend should bind the reader to a captured account and include that account in the identity/cache/remount boundary. It must raise `INBOX_CONTEXT_CHANGED` or `AbortError` when identity changes so the optional-team recovery does not swallow it. Account selection itself is deliberately not implemented in this branch.

Default transport is read-only. Copy controls receive canonical PR browser URLs; Ask Hermes inserts a draft containing only the URL and a no-mutation instruction. No notification endpoints, unread/read/Done state, or inbox GitHub mutations remain.

## Refresh and gaps

The shared QueryClient refreshes active/open/foreground views every 60 seconds, pauses periodic work after errors and refreshes stale views on focus. Every page is context-guarded before and after transport. Hiding a pane cannot cancel a request already sent.

Not implemented: custom saved views/default view settings, open/closed switch, unread update indicators, Copilot-on-your-behalf authored expansion, autocomplete/project filters, avatar/filter links, exact GitHub internal precedence, and saved collapse state. Browser-native details/summary supplies keyboard-accessible collapse; other controls reuse Hermes SDK components. UI text is labels and terse runtime status only.

The production GraphQL document was exercised read-only against GitHub: personal review search returned two PRs with expected field shapes, team-review-requested-user was accepted (zero matches for that account), and public cli/cli search returned 50 nodes with hasNextPage true. This verifies API shape and qualifier acceptance, not a positive team-membership fixture or the installed desktop shell transport. The existing large-payload shell redaction problem remains fail-closed; the account/backend worker owns its resolution.

Node component tests inspect integrated production JSX with SDK stubs, not installed desktop appearance. Real QueryObserver tests require an existing dependency root via `HERMES_QUERY_ROOT`; no packages are installed by this work.

## Sources

- [March 26, 2026: new PR dashboard preview](https://github.blog/changelog/2026-03-26-new-pull-requests-dashboard-is-in-public-preview/): inbox, saved views, repo/update filters, default authored/assigned/involves/review views.
- [April 23, 2026: opt-out preview](https://github.blog/changelog/2026-04-23-global-pull-requests-dashboard-moves-to-opt-out-public-preview/): org filtering, drafts/waiting, distinct personal/team sections, collapse.
- [Current search documentation](https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests#search-by-pull-request-review-status-and-reviewer): `user-review-requested:@me`, `team-review-requested-user:USERNAME`, `team-review-requested:ORG/TEAM`; ordinary `review-requested:USERNAME` includes team requests.
- [Current dashboard documentation](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/viewing-all-of-your-issues-and-pull-requests).
- [Current GraphQL pull request reference](https://docs.github.com/en/graphql/reference/pulls): merge-state and review-decision fields; enum descriptions additionally verified through live schema introspection.
