# Native Desktop Integration

## Navigation and pane lifecycle

GitHub remains a permanent sidebar navigation entry while the plugin is enabled. The navigation entry opens the `/github` workspace page. The GitHub tool pane belongs to the native right-hand tab group, rather than creating a second split beside the workspace. The command palette provides separate page and pane actions.

The titlebar and the pane's own **Close** button remove only the pane contribution through the public `ctx.register` disposer. Reopening re-registers the same pane ID and calls `host.revealPane('githermes:pane')`. Navigation, page and commands stay registered, and the user's closed choice persists in plugin storage.

### Stock-host compatibility

Both freshly fetched upstream main and the matched official `0.21.5+2271` source lack `host.togglePane` and `closeBehavior: 'hide'`; native Close disables a single-pane plugin. This branch therefore marks the pane `uncloseable:true` and supplies its own Close action. Native tab X/middle-click/bulk-close are unavailable for GitHub, and the native group minimize affordance is suppressed while it contains this pane. External side collapse also remains a visibility-atom limitation: an active pane behind a collapsed side needs two titlebar presses, or one explicit palette Open. No host patch is required for this alternative. See [exact provenance, tests and remaining limitations](stock-2271-compatibility.md).

Fork changes are not evidence of a shipped official Windows feature. This branch has not been verified on Windows or installed into the user's app.

Existing user-customized layouts remain authoritative. Changing the default placement does not forcibly move an already-positioned tab. Drag GitHub into the right tab group or use an explicit layout reset when migrating an older layout; do not reset the user's entire layout automatically.

## Design contract

Use the actual Hermes SDK controls, not lookalike components. Native badges, status dots, buttons, checkboxes, empty states, and popovers own their geometry and semantic colors. Custom list, diff, and timeline composition uses host tokens without overriding SDK internals. Repository label names remain visible and filterable; arbitrary repository label colors do not override the active theme.

## Pull request inbox

Inbox is the cross-repository pull request dashboard at `https://github.com/pulls/inbox`, not notifications. It has six collapsible PR sections, authored/assigned/involves/review views, repository/organization/update filters, canonical link copying and insert-only draft handoff. The old notifications API and read/Done mutations have been removed.

See [PR inbox](pr-inbox.md) for official sources, exact public-API classification rules, account transport seam, refresh behavior and explicit parity limits. Unknown mergeability is never ready; denied team searches and bounded results are labeled rather than presented as complete.

## Verification boundaries

Node tests exercise plugin contribution declarations, navigation actions, pure logic, and component contracts using test-only SDK stubs. Real SDK/native renderer tests and isolated Linux Electron smoke now pass on both official source revisions: close/reopen, retained sidebar navigation, unchanged plugin decisions, Files grouping and closed-state reload. No fork dependency or host source modification was used. See the linked compatibility report for source SHAs, evidence and remaining Windows, custom-placement and appearance coverage limits.
