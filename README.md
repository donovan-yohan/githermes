# GitHermes

GitHub PRs & Issues as a right workspace pane in [Hermes Desktop](https://hermes-agent.nousresearch.com/docs/user-guide/desktop).

> **Community plugin.** GitHermes is an open-source, independent project. It is **not** an official Nous Research product and is not developed or maintained by the Hermes team. It works with Hermes Desktop through its public plugin API.

A desktop plugin (`@hermes/plugin-sdk`) that shows your repository's PRs and issues in a dockable pane — conversation, reviews, commits, checks, files, and in-pane merge — themed with Hermes `--ui-*` variables. A private Python backend runs each GitHub operation with the selected authenticated `gh` identity. Tokens never enter the renderer; selection never switches global CLI authentication.

| PR list | PR detail |
| --- | --- |
| ![PR list pane](docs/pr-list.png?v=3) | ![PR detail view](docs/pr-detail.png?v=3) |

| Conversation (inline review) | Commits |
| --- | --- |
| ![Inline review threads](docs/pr-conversation.png) | ![Commits tab](docs/pr-commits.png) |

| Issues |
| --- |
| ![Issue list](docs/issue-list.png) |

## Features

- **GitHub accounts** — native selector when multiple identities are available, connection/profile-scoped saved choice, isolated caches and stale-write fencing
- **PR list** — state pills, `+N / −N`, relative timestamps, **CI** (`passing / pending / failing`) and **review** (`approved / changes / required`) chips, exact `#N` search (`#42` does not match `#142`)
- **Session chip + repo picker** — PR for the active session branch (same join as the core review pane); 32px pill with `https://github.com/{owner}.png` avatar
- **PR / Issue header** — kicker, grouped meta chips, title glued to `#`, **Merge** action on open PRs (`squash / merge / rebase`, optional delete-branch, `GH_PROMPT_DISABLED=1`)
- **Conversation** — `gh-timeline` rail, GFM subset (quotes, task lists, tables, `<details>`, strikethrough; raw HTML stripped), icon-only Quote → active composer, compact checks strip (`Blocked` / `Waiting` / `All passed`)
- **Inline review threads** — `file:line` chip (`original_line` fallback), collapsed diff hunk, replies grouped by `in_reply_to_id`
- **Jump to latest** — floating control on the Radix viewport only (nested code/table scrollers ignored); remeasures when the detail DOM mounts
- **Commits** — same rail; each row is a `<details>` with lazy-loaded body / `+−` / files; SHA + external link do not toggle
- **Files** — unified hunks per file, line numbers, theme diff colors, `A/D/M/R` badge; unboxed header, border on the diff body
- **Issues** — label chips in the label's own color, black/white text via W3C relative luminance
- **Theme** — field surfaces on `--ui-editor-surface-background` (matte/glass inherited from Desktop); cards on `--ui-bg-quaternary`; container queries at `<360` / `<300` / `<240`

## Requirements

> **Desktop compatibility:** Keeping GitHub navigation after closing its pane requires the companion host patch implementing `closeBehavior: 'hide'`. Older desktops may disable the plugin on Close; installing this plugin alone does not fix that host behavior. See [native desktop integration](docs/native-desktop-integration.md).

Repository / Inbox mode is shared between pane and page. Inbox is the [GitHub pull request inbox](https://github.com/pulls/inbox): six collapsible sections, authored/assigned/involves/review views, multi-repository/organization/update filters, copy links and draft handoff. Personal and team review requests use separate documented search qualifiers. See [classification rules and parity gaps](docs/pr-inbox.md).


- Hermes Desktop
- [`gh`](https://cli.github.com/) installed and authenticated, supporting `gh auth token --user`
- An explicit profile-scoped `GH_CONFIG_DIR` and the enabled Python backend
- For local multi-profile Desktop, the companion [routing patch](integration/hermes-profile-routing.patch); see [account installation and verification](docs/account-execution-feasibility.md)

## Install

```bash
hermes plugins enable githermes
```

First install this checkout as a trusted unified user package in the backend's plugin directory, with both `desktop/` and `dashboard/`. The account integration is not yet published upstream. Enable it with the command above, then reload the backend to mount its Python routes. **Copying only `desktop/plugin.js` is no longer sufficient.** Follow the [installation requirements](docs/account-execution-feasibility.md#required-installation-not-performed-by-this-change), including the local-profile routing patch where required.

### Upgrading from `github-prs`

The plugin **id** changed (`github-prs` → `githermes`), so the old install must be removed first — delete the old folder (`~/.hermes/desktop-plugins/github-prs/` or `~/.hermes/plugins/github-prs/`), then install fresh. One-time cost: the saved repository in the picker resets (plugin storage is namespaced by id).

## Development notes

- Disk plugins load **uncompiled**: UI is written with `jsx()`/`jsxs()` calls, no JSX syntax, no build step.
- Only `@hermes/plugin-sdk`, `react`, and `react/jsx-runtime` are importable.
- Tailwind classes must already exist in the app's compiled CSS — arbitrary `var()` bracket forms (`bg-[var(--x)]`) are silently dead at runtime. Use the paren shorthand (`text-(--ui-text-tertiary)`) or scoped `<style>` blocks with real theme variables.
- GitHub payloads use structured JSON over authenticated plugin REST, with forced host redaction before serialization. Lists grow from 30 to a 120-row cap; comments/files use bounded pagination. No GitHub output passes through shell/base64 chunking.

## Status & contributing

Early stage — expect bugs; reports and PRs are very welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT

---

🇧🇷 **PT-BR:** pane de PRs e Issues no Hermes Desktop. Lista com CI/review, busca `#N` exata, header preenchido, merge no pane, timeline com threads inline (`file:line` + diff), jump-to-latest no viewport, commits em `<details>` lazy, diffs por hunk, labels com contraste W3C. Backend privado com contas GitHub por operação, sem alterar a conta global do `gh`.
