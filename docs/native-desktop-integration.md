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

## Pull request inbox

Inbox is the cross-repository pull request dashboard at `https://github.com/pulls/inbox`, not notifications. It has six collapsible PR sections, authored/assigned/involves/review views, repository/organization/update filters, canonical link copying and insert-only draft handoff. The old notifications API and read/Done mutations have been removed.

See [PR inbox](pr-inbox.md) for official sources, exact public-API classification rules, account transport seam, refresh behavior and explicit parity limits. Unknown mergeability is never ready; denied team searches and bounded results are labeled rather than presented as complete.

## Verification boundaries

Node tests exercise plugin contribution declarations, navigation actions, pure logic, and component contracts using test-only SDK stubs. They do not establish rendered parity or installed Electron behavior. The companion host tests exercise the actual tree store and contribution registry. Release verification must additionally exercise an actual Desktop renderer: close/reopen, retained sidebar navigation, tab grouping, layout persistence, narrow widths, and light/dark appearance.
