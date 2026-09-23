# Native Desktop Integration

## Navigation and pane lifecycle

GitHub remains a permanent sidebar navigation entry while the plugin is enabled. The navigation entry opens the `/github` workspace page. The GitHub tool pane belongs to the native right-hand tab group, rather than creating a second split beside the workspace. The command palette provides separate page and pane actions.

The pane declares `closeBehavior: 'hide'`. Closing it should dismiss that pane only, keeping the GitHub route, navigation entry, and commands registered. Reopening uses `host.revealPane('githermes:pane')`; older hosts retain the legacy reveal-event fallback. Explicitly disabling the plugin in Capabilities still unloads its contributions.

### Required host change

The hide-on-close policy requires Hermes Desktop support for `PaneData.closeBehavior`. The companion implementation is commit `962febc2eb87ce239b38d8e55078115c76434da0` on local branch `feat/desktop-pane-close-hide`.

Older Desktop builds ignore this field and may still disable a single-pane plugin when its tab closes. The presence of `host.revealPane` alone does not establish support. Updating the plugin without updating the host is not a complete fix.

Existing user-customized layouts remain authoritative. Changing the default placement does not forcibly move an already-positioned tab. Drag GitHub into the right tab group or use an explicit layout reset when migrating an older layout; do not reset the user's entire layout automatically.

## Design contract

Use the actual Hermes SDK controls, not lookalike components. Native badges, status dots, buttons, checkboxes, empty states, and popovers own their geometry and semantic colors. Custom list, diff, and timeline composition uses host tokens without overriding SDK internals. Repository label names remain visible and filterable; arbitrary repository label colors do not override the active theme.

## Inbox scope and API limits

The Inbox combines notifications with a separate live search for open pull requests requesting the authenticated user's review. Notification reasons are historical signals: `review_requested` can include team requests and does not establish that a review is still pending. The live personal-review search is deliberately labeled separately.

Repository and organization filters must report the scope actually searched. Account-wide notification scans are bounded; organization filtering can exclude newer results without reaching older matching threads. Show truncation explicitly rather than presenting the loaded count as a total. Targeted repository endpoints reduce that gap.

The public REST notifications API does not offer full parity with the web inbox's Saved/Done archive views. Keep a link to the full GitHub inbox for unsupported views. Mark-read actions require exact-thread readback. A successful Done request is not proof of archive state: thread GET does not expose a Done flag.

Copy-link actions use canonical GitHub browser URLs, not REST API URLs. Ask Hermes inserts a draft only. Opening the panel, filtering, and rendering must never mutate GitHub state or submit a chat message.

References: [GitHub notifications API](https://docs.github.com/en/rest/activity/notifications) and [Managing the GitHub inbox](https://docs.github.com/en/subscriptions-and-notifications/how-tos/viewing-and-triaging-notifications/managing-notifications-from-your-inbox).

## Refresh semantics

Inbox refresh uses the desktop SDK's shared QueryClient (no manual interval loop). **Needs your review** re-runs its live search every 60 seconds while its pane/page is active, the gateway is `open`, and the desktop window is foregrounded. Hiding the pane, disconnecting, backgrounding the window, or unmounting stops periodic work. Returning to a stale view or window refetches it; a fresh cache is reused.

Notifications retain `X-Poll-Interval` from `gh api --include`. Their next poll waits at least the largest server interval across every page/repository in the bounded scan, with a conservative 60-second minimum. Stale-on-focus/reconnect uses the same interval, not an unconditional 60-second threshold. A changed header adjusts the next timer. If any response omits the header or supplies an invalid/overflowing interval, periodic notification polling is disabled; stale-on-focus (after 60 seconds) and the explicit **Refresh** action remain available. Periodic refresh stops after errors, with no automatic retry loop; errors stay visible and focus/manual refresh can recover. Explicit Refresh and post-mutation invalidation are user-triggered refreshes, not periodic polls.

Already-dispatched gateway commands cannot be canceled by hiding the pane. Connection/profile identity guards still fence every subsequent transport dispatch; cached queries remain identity- and filter-scoped. Polling does not expand pagination caps or make bounded scans complete.

## Verification boundaries

Node tests exercise plugin contribution declarations, navigation actions, pure logic, and component contracts using test-only SDK stubs. They do not establish rendered parity or installed Electron behavior. The companion host tests exercise the actual tree store and contribution registry. Release verification must additionally exercise an actual Desktop renderer: close/reopen, retained sidebar navigation, tab grouping, layout persistence, narrow widths, and light/dark appearance.
