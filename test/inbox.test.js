import test from 'node:test'
import assert from 'node:assert/strict'
import * as api from '../desktop/plugin.js'
import { host, atom, SegmentedControl } from '@hermes/plugin-sdk'
const context = () => {
  host.state.gateway = atom('open'); host.state.connectionId = atom('local')
  host.state.profile = atom('ebi'); host.state.activeSessionId = atom('s')
  return api.inboxIdentity()
}
const nodes = tree => {
  const out = []; const visit = n => { if (!n || typeof n !== 'object') return; if (Array.isArray(n)) return n.forEach(visit); out.push(n); visit(n.props?.children) }
  visit(tree); return out
}
test('filters normalize multi-repo keys and separate identity/view/recency/org', () => {
  assert.deepEqual(api.inboxQueryKey({ repositories: 'Acme/B,acme/a,ACME/B' }, 'a'), api.inboxQueryKey({ repositories: ['acme/a', 'acme/b'] }, 'a'))
  for (const value of [{ view: 'reviews' }, { view: 'authored' }, { view: 'assigned' }, { view: 'involves' }, { updated: '7' }, { organization: 'acme' }, { repositories: 'acme/a' }]) assert.notDeepEqual(api.inboxQueryKey(value), api.inboxQueryKey({}))
  assert.notDeepEqual(api.inboxQueryKey({}, 'a'), api.inboxQueryKey({}, 'b'))
  for (const repositories of ['../a', 'a/..', 'https://github.com/acme/app', 'a/b;touch', 'a/b:c', 'a/1,a/2,a/3,a/4,a/5,a/6']) assert.throws(() => api.inboxFilters({ repositories }))
  assert.throws(() => api.inboxFilters({ organization: 'acme org:evil' }))
})
test('recency uses a rolling timestamp, not midnight rounding', () => {
  assert.match(api.inboxSearch({ updated: '1' }, 'direct', new Date('2026-09-23T12:34:56Z')), /updated:>=2026-09-22T12:34:56\.000Z/)
})

test('scopes and supported search qualifiers do not conflate personal/team review', () => {
  assert.equal(api.inboxSearch({ organization: 'acme' }, 'direct'), 'is:pr is:open user-review-requested:@me org:acme sort:updated-desc')
  assert.match(api.inboxSearch({}, 'team'), /team-review-requested-user:@me/)
  assert.match(api.inboxSearch({}, 'involves'), /involves:@me/)
  assert.equal(api.inboxSearch({ repositories: 'acme/b,other/a,acme/a', organization: 'acme' }, 'authored'), 'is:pr is:open author:@me repo:acme/a repo:acme/b sort:updated-desc')
  assert.equal(api.inboxSearch({ repositories: 'other/app', organization: 'acme' }, 'direct'), null)
})
test('disjoint repo/org selection never dispatches; single views issue only one source search', async () => {
  const noRead = () => assert.fail('unrelated data must not fetch')
  assert.equal((await api.loadGitHubInbox({ organization: 'acme', repositories: 'other/app' }, noRead)).items.length, 0)
  for (const view of ['authored', 'assigned', 'involves']) {
    const calls = []
    await api.loadGitHubInbox({ view }, async request => { calls.push(request); return { data: { search: { nodes: [], issueCount: 0, pageInfo: { hasNextPage: false } } } } })
    assert.equal(calls.length, 1)
    assert.match(calls[0].variables.search, new RegExp(({ authored: 'author', assigned: 'assignee', involves: 'involves' })[view] + ':@me'))
  }
})
test('links and drafts accept canonical PR URLs only', () => {
  for (const url of ['javascript:alert(1)', 'https://evil.test/a/b/pull/1', 'https://github.com/a/b/issues/1', 'https://api.github.com/repos/a/b/pulls/1']) assert.equal(api.inboxItemUrl({ url }), '')
  assert.equal(api.inboxItemUrl({ url: 'https://github.com/a/b/pull/1' }), 'https://github.com/a/b/pull/1')
  assert.equal(api.inboxDraft({}), '')
})
test('mode remains reachable without repository discovery in pane and page', () => {
  context(); api.githubAccountState.set({ context: JSON.stringify(['local', 'ebi']), login: 'alpha', ready: true, generation: 1, epoch: 1 }); globalThis.__ghTestQuery = () => assert.fail('no discovery in shell')
  try {
    api.setGitHubMode('inbox')
    for (const page of [false, true]) {
      const all = nodes(api.GitHubSurface({ page }))
      assert.ok(all.some(n => n.type === SegmentedControl && n.props.options.some(o => o.id === 'inbox')))
      assert.ok(all.some(n => n.key === JSON.stringify(['local', 'ebi', 'alpha', 1])))
      assert.ok(all.some(n => n.type === api.GitHubInbox))
    }
  } finally { delete globalThis.__ghTestQuery }
})
test('account/context change during final team read rejects instead of returning stale partial data', async () => {
  const identity = context()
  const opts = api.inboxQueryOptions({ view: 'reviews' }, identity, true, 'open', async request => {
    if (request.variables.search.includes('team-review-requested-user:')) host.state.profile.set('other')
    return { data: { search: { nodes: [], issueCount: 0, pageInfo: { hasNextPage: false } } } }
  })
  await assert.rejects(opts.queryFn(), /context changed/)
})

test('read transport checks context before and after every page; disconnected never dispatches', async () => {
  const identity = context(); let calls = 0
  const opts = api.inboxQueryOptions({}, identity, true, 'open', async () => {
    calls++; host.state.profile.set('other')
    return { data: { search: { nodes: [], issueCount: 0, pageInfo: { hasNextPage: false } } } }
  })
  await assert.rejects(opts.queryFn(), /context changed/)
  assert.equal(calls, 1)
  await assert.rejects(opts.queryFn(), /context changed/)
  assert.equal(calls, 1)
  assert.equal(api.inboxQueryOptions({}, identity, false, 'open').enabled, false)
  assert.equal(api.inboxQueryOptions({}, identity, true, 'connected').enabled, false)
})
