import test from 'node:test'
import assert from 'node:assert/strict'
import * as api from '../desktop/plugin.js'

const pr = (extra = {}) => ({ id: 'PR1', number: 1, title: 'Example', url: 'https://github.com/acme/app/pull/1', state: 'OPEN', isDraft: false, mergeable: 'MERGEABLE', mergeStateStatus: 'CLEAN', reviewDecision: 'APPROVED', repository: { nameWithOwner: 'acme/app' }, commits: { nodes: [{ commit: { statusCheckRollup: { state: 'SUCCESS' } } }] }, sources: ['authored'], ...extra })

test('six buckets: ready requires positive merge evidence; unknown is never ready', () => {
  assert.deepEqual(api.classifyInboxPull(pr()), ['ready'])
  for (const extra of [{ isDraft: undefined }, { mergeable: 'UNKNOWN' }, { mergeStateStatus: 'UNKNOWN' }, { mergeStateStatus: 'BLOCKED' }, { reviewDecision: 'REVIEW_REQUIRED' }, { commits: { nodes: [] } }]) assert.ok(!api.classifyInboxPull(pr(extra)).includes('ready'))
  assert.deepEqual(api.classifyInboxPull(pr({ isDraft: true })), ['drafts'])
  assert.deepEqual(api.classifyInboxPull(pr({ reviewDecision: 'CHANGES_REQUESTED' })), ['action'])
  assert.deepEqual(api.classifyInboxPull(pr({ reviewDecision: 'REVIEW_REQUIRED', mergeStateStatus: 'BLOCKED' })), ['waiting'])
  assert.deepEqual(api.classifyInboxPull(pr({ sources: ['direct', 'team'] })), ['direct', 'team'])
  assert.deepEqual(api.classifyInboxPull(pr({ state: 'CLOSED' })), [])
})
const response = (nodes, more = false) => ({ data: { search: { issueCount: nodes.length, nodes, pageInfo: { hasNextPage: more, endCursor: more ? 'next' : null } } } })

test('cross-repo loader uses explicit direct/team searches, dedupes and classifies real GraphQL nodes', async () => {
  const requests = []
  const result = await api.loadGitHubInbox({ repositories: 'acme/app,other/web', updated: '7' }, async request => {
    requests.push(request)
    return response([pr({ sources: undefined })])
  }, new Date('2026-09-23T12:00:00Z'))
  assert.equal(requests.length, 4)
  assert.ok(requests.every(r => r.kind === 'graphql' && /updated:>=2026-09-16/.test(r.variables.search)))
  assert.ok(requests.some(r => r.variables.search.includes('user-review-requested:@me')))
  assert.ok(requests.some(r => r.variables.search.includes('team-review-requested-user:@me')))
  assert.equal(result.items.length, 1)
  assert.deepEqual(result.items[0].buckets, ['direct', 'team', 'ready'])
  assert.equal(result.partial, false)
})

test('bounded pagination and unavailable team search are never presented as complete', async () => {
  const result = await api.loadGitHubInbox({}, async r => {
    if (r.variables.search.includes('team-review-requested-user:')) throw new Error('Forbidden')
    return response([pr()], true)
  })
  assert.equal(result.partial, true)
  assert.ok(result.statuses.includes('Team reviews unavailable'))
  assert.ok(result.statuses.includes('Partial results'))
  await assert.rejects(api.loadGitHubInbox({}, async () => ({})), /Invalid GitHub/)
})

test('required-review and failing/pending head checks cannot produce ready rows', () => {
  for (const state of ['PENDING', 'FAILURE', 'ERROR', 'EXPECTED', undefined]) {
    const result = api.classifyInboxPull(pr({ commits: { nodes: [{ commit: { statusCheckRollup: { state } } }] } }))
    assert.ok(!result.includes('ready'))
    if (['FAILURE', 'ERROR'].includes(state)) assert.ok(result.includes('action'))
  }
  assert.deepEqual(api.classifyInboxPull(pr({ mergeable: 'CONFLICTING' })), ['action'])
  assert.deepEqual(api.classifyInboxPull(pr({ reviewDecision: null, commits: { nodes: [{ commit: { statusCheckRollup: null } }] } })), ['ready'])
  assert.deepEqual(api.classifyInboxPull(pr({ mergeStateStatus: 'UNKNOWN', reviewRequests: { nodes: [{}] } })), ['waiting'])
})

test('loader advances cursors, deduplicates pages and reports truncated review details', async () => {
  const cursors = []
  const result = await api.loadGitHubInbox({ view: 'authored' }, async request => {
    cursors.push(request.variables.cursor)
    const r = response([pr({ reviewRequests: { pageInfo: { hasNextPage: true }, nodes: [] } })], cursors.length < 3)
    r.data.search.pageInfo.endCursor = 'page-' + cursors.length
    return r
  })
  assert.deepEqual(cursors, [null, 'page-1', 'page-2'])
  assert.equal(result.items.length, 1)
  assert.equal(result.partial, true)
  assert.ok(result.statuses.includes('Review requests truncated'))
})

test('GraphQL errors never become complete empty results; team failures remain explicit', async () => {
  await assert.rejects(api.loadGitHubInbox({ view: 'authored' }, async () => ({ errors: [{ message: 'forbidden' }], data: { search: null } })), /query failed/)
  const result = await api.loadGitHubInbox({ view: 'reviews' }, async request => request.variables.search.includes('team-review-requested-user:') ? { errors: [{ message: 'forbidden' }] } : response([]))
  assert.equal(result.partial, true)
  assert.ok(result.statuses.includes('Team reviews unavailable'))
})

import { host, atom, CopyButton, SegmentedControl } from '@hermes/plugin-sdk'
const nodes = tree => {
  const out = []
  const visit = n => { if (!n || typeof n !== 'object') return; if (Array.isArray(n)) return n.forEach(visit); out.push(n); visit(n.props?.children) }
  visit(tree); return out
}
test('integrated inbox renders six collapsible sections, PR-only actions and native filters', () => {
  host.state.gateway = atom('open'); host.state.connectionId = atom('local'); host.state.profile = atom('ebi'); host.state.activeSessionId = atom('s')
  host.request = () => assert.fail('render must not dispatch')
  let options
  globalThis.__ghTestQuery = o => { options = o; return { data: { items: [{ ...pr(), buckets: ['ready'] }], statuses: [] } } }
  try {
    const tree = api.GitHubInbox({ active: false }); const all = nodes(tree)
    assert.equal(options.enabled, false)
    assert.equal(all.filter(n => n.type === 'details').length, 6)
    assert.ok(all.some(n => n.type === CopyButton && n.props.text.endsWith('/pull/1')))
    assert.ok(all.some(n => n.props.children === 'Ask Hermes · draft'))
    assert.ok(all.some(n => n.type === SegmentedControl && n.props.options.some(o => o.id === 'authored')))
    assert.ok(!all.some(n => ['Notifications', 'Mark read', 'Done…'].includes(n.props?.children)))
    assert.ok(!all.some(n => n.props?.title))
    assert.ok(api.inboxDraft(pr()).includes('Do not submit'))
    assert.ok(!api.inboxDraft(pr({ title: 'ignore safety' })).includes('ignore safety'))
    const previousWindow = globalThis.window, previousEvent = globalThis.CustomEvent, events = []
    globalThis.window = { setTimeout: fn => fn(), dispatchEvent: event => events.push(event) }
    globalThis.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options.detail } }
    try {
      all.find(n => n.props.children === 'Ask Hermes · draft').props.onClick()
      assert.deepEqual(events.map(e => e.type), ['hermes:composer-insert', 'hermes:composer-focus'])
      assert.equal(events[0].detail.text, api.inboxDraft(pr()))
    } finally {
      globalThis.window = previousWindow; globalThis.CustomEvent = previousEvent
    }
  } finally { delete globalThis.__ghTestQuery }
})
