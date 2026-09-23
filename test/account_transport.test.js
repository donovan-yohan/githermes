import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { host, atom, Select, SelectTrigger, Button } from '@hermes/plugin-sdk'
import plugin, * as api from '../desktop/plugin.js'

const nodes = tree => {
  const out = []
  const walk = value => { if (!value || typeof value !== 'object') return; if (Array.isArray(value)) return value.forEach(walk); out.push(value); walk(value.props?.children) }
  walk(tree); return out
}
let nextId = 0
function setup() {
  const connection = 'account-test-' + (++nextId)
  host.state.gateway = atom('open'); host.state.connectionId = atom(connection); host.state.profile = atom('alpha-profile'); host.state.activeSessionId = atom('s')
  host.request = () => assert.fail('GitHub must never reach shell.exec')
  const saved = new Map(), calls = [], leases = new Map()
  let accounts = [{ login: 'alpha', active: true }, { login: 'beta', active: false }]
  let delay = null, selectionBackend = connection
  plugin.register({ register() {}, storage: { get: key => saved.get(key), set: (key, value) => saved.set(key, value) }, rest: async (path, options = {}) => {
    calls.push({ path, options })
    if (path.startsWith('/accounts?')) return { accounts, backend: connection }
    if (path.startsWith('/selection?')) {
      const previous = options.body.lease ? leases.get(options.body.lease) : null
      if (previous) assert.equal(options.body.epoch, previous.epoch)
      const result = { backend: selectionBackend, login: options.body.login, lease: previous?.lease || 'opaque-' + leases.size, epoch: (previous?.epoch || 0) + 1 }
      leases.set(result.lease, result)
      return result
    }
    if (path.startsWith('/revoke?')) {
      const previous = leases.get(options.body.lease)
      assert.equal(options.body.epoch, previous.epoch)
      const result = { ...previous, epoch: previous.epoch + 1 }
      leases.set(result.lease, result)
      return result
    }
    assert.ok(path.startsWith('/operation?'))
    const selected = leases.get(options.body.lease)
    assert.equal(options.body.epoch, selected.epoch)
    const data = options.body.operation.path === 'graphql'
      ? { data: { search: { nodes: [], issueCount: 0, pageInfo: { hasNextPage: false } } } }
      : { login: selected.login, unicode: '日本語 🐙' }
    if (delay) await delay
    return { data, backend: connection }
  } })
  return { calls, saved, setSelectionBackend: value => { selectionBackend = value }, setAccounts: value => { accounts = value }, setDelay: value => { delay = value } }
}

test('integrated discovery, A→B→A cache epochs and per-context persistence never mutate global auth', async () => {
  const fixture = setup()
  await api.refreshGitHubAccounts()
  const a = api.captureGitHubScope(), keyA = api.scopedGitHubQueryKey(['githermes', 'repos'])
  assert.equal(a.login, 'alpha')
  assert.equal((await api.githubOperation({ operation: 'github.api', path: 'user' })).login, 'alpha')
  await api.selectGitHubAccount('beta')
  assert.equal((await api.githubOperation({ operation: 'github.api', path: 'user' })).login, 'beta')
  await api.selectGitHubAccount('alpha')
  const a2 = api.captureGitHubScope()
  assert.notEqual(a.generation, a2.generation)
  assert.notEqual(a.epoch, a2.epoch)
  assert.notDeepEqual(keyA, api.scopedGitHubQueryKey(['githermes', 'repos']))
  const count = fixture.calls.length
  await assert.rejects(api.githubOperation({ operation: 'issue.close', repo: 'a/b', number: 1 }, a), { code: 'INBOX_CONTEXT_CHANGED' })
  assert.equal(fixture.calls.length, count, 'old confirmation must fail before dispatch')
  assert.equal(fixture.saved.get(`account:${a.context}`), 'alpha')
  assert.ok([...fixture.saved.values()].every(v => typeof v === 'string' && !v.includes('opaque-')))
  assert.ok(fixture.calls.every(call => call.path.includes('profile=alpha-profile')))
  assert.ok(!JSON.stringify(fixture.calls).includes('GH_TOKEN'))
})

test('late reads and pre-switch mutations fail closed; GraphQL uses structured backend JSON', async () => {
  const fixture = setup(); await api.refreshGitHubAccounts()
  let release
  fixture.setDelay(new Promise(resolve => { release = resolve }))
  const pending = api.githubOperation({ operation: 'github.api', path: 'user' })
  await api.selectGitHubAccount('beta')
  release()
  await assert.rejects(pending, { code: 'INBOX_CONTEXT_CHANGED' })
  fixture.setDelay(null)
  await api.loadGitHubInbox({ view: 'authored' })
  const graph = fixture.calls.find(c => c.options.body?.operation?.path === 'graphql')
  assert.equal(graph.options.body.operation.operation, 'github.api')
  assert.equal(graph.options.body.operation.method, 'POST')
  assert.equal(graph.options.body.operation.body.variables.cursor, null)
  assert.ok(graph.options.body.operation.body.query.startsWith('query'))
  const captured = api.captureGitHubScope(), count = fixture.calls.filter(c => c.path.startsWith('/operation')).length
  host.state.profile.set('other-profile')
  await assert.rejects(api.githubOperation({ operation: 'pr.review', repo: 'a/b', number: 1 }, captured), { code: 'INBOX_CONTEXT_CHANGED' })
  assert.equal(fixture.calls.filter(c => c.path.startsWith('/operation')).length, count)
  await api.refreshGitHubAccounts()
  assert.notEqual(api.captureGitHubScope().context, captured.context)
  assert.ok(fixture.calls.some(c => c.path === '/revoke?profile=other-profile'))
})

test('native selector only for multiple identities; missing persisted login never falls back', async () => {
  const fixture = setup(); await api.refreshGitHubAccounts()
  let state = api.captureGitHubScope()
  const selector = api.GitHubAccountSelector()
  assert.equal(selector.type, Select)
  assert.ok(nodes(selector).some(n => n.type === SelectTrigger && n.props['aria-label'] === 'GitHub account'))
  assert.ok(!nodes(selector).some(n => n.props.title))
  api.githubAccountState.set({ ...state, accounts: [{ login: 'alpha' }] })
  assert.equal(api.GitHubAccountSelector(), null)
  api.githubAccountState.set(state)
  await api.selectGitHubAccount('beta')
  fixture.setAccounts([{ login: 'alpha', active: true }])
  const count = fixture.calls.filter(c => c.path.startsWith('/selection')).length
  await api.refreshGitHubAccounts(true)
  state = api.captureGitHubScope()
  assert.equal(state.ready, false)
  assert.equal(state.login, 'beta')
  assert.equal(state.error, 'GitHub account unavailable')
  assert.equal(fixture.calls.filter(c => c.path.startsWith('/selection')).length, count)
  const recovery = api.GitHubAccountSelector()
  assert.equal(recovery.type, Button)
  assert.equal(recovery.props.children, 'Use alpha')
  recovery.props.onClick()
  await Promise.resolve()
  assert.equal(api.captureGitHubScope().login, 'alpha')
})

test('scope refresh hides stale surfaces and disables controls until selection is confirmed', async () => {
  setup(); await api.refreshGitHubAccounts()
  const previous = api.captureGitHubScope()
  api.githubAccountState.set({ ...previous, pending: true, ready: false })
  assert.equal(api.GitHubAccountSelector().props.disabled, true)
  const pending = nodes(api.GitHubSurface())
  assert.ok(!pending.some(n => n.type === api.GitHubInbox))
  assert.equal(pending.find(n => n.type === Button && n.props.children === 'Refresh accounts').props.disabled, true)
  api.githubAccountState.set(previous)
  const ready = nodes(api.GitHubSurface())
  assert.ok(ready.some(n => n.key?.includes('alpha')))
  host.state.gateway.set('closed')
  assert.equal(api.GitHubAccountSelector().props.disabled, true)
  assert.equal(nodes(api.GitHubSurface()).find(n => n.type === Button && n.props.children === 'Refresh accounts').props.disabled, true)
})

test('synchronous profile A→B→A invalidates captured writes even before React effects', async () => {
  const fixture = setup(); await api.refreshGitHubAccounts()
  const before = api.captureGitHubScope()
  host.state.profile.set('beta-profile'); host.state.profile.set('alpha-profile')
  assert.throws(() => api.assertGitHubScope(before), { code: 'INBOX_CONTEXT_CHANGED' })
  await api.refreshGitHubAccounts()
  assert.equal(api.captureGitHubScope().ready, true)
  assert.notEqual(api.captureGitHubScope().generation, before.generation)
  assert.ok(fixture.calls.some(c => c.path.startsWith('/revoke')))
})

test('a Desktop GET/POST split across backends fails closed instead of enabling writes', async () => {
  const fixture = setup(); fixture.setSelectionBackend('different-process')
  await assert.rejects(api.refreshGitHubAccounts(), /backend routing changed/)
  assert.equal(api.captureGitHubScope().ready, false)
  const count = fixture.calls.filter(c => c.path.startsWith('/operation')).length
  await assert.rejects(api.githubOperation({ operation: 'pr.merge', repo: 'a/b', number: 1 }))
  assert.equal(fixture.calls.filter(c => c.path.startsWith('/operation')).length, count)
})

test('rendered query facade changes keys and rejects old-account refresh functions', async () => {
  setup(); await api.refreshGitHubAccounts()
  let options, reads = 0
  const read = async () => { reads++; return { data: { search: { nodes: [], issueCount: 0, pageInfo: { hasNextPage: false } } } } }
  globalThis.__ghTestQuery = value => { options = value; return {} }
  try {
    api.GitHubInbox({ read })
    const old = options
    assert.equal(old.enabled, true)
    await api.selectGitHubAccount('beta')
    api.GitHubInbox({ read })
    assert.notDeepEqual(old.queryKey, options.queryKey)
    await assert.rejects(old.queryFn(), { code: 'INBOX_CONTEXT_CHANGED' })
    assert.equal(reads, 0)
    await options.queryFn()
    assert.equal(reads, 4)
  } finally { delete globalThis.__ghTestQuery }
})

test('repository projections preserve rendered contracts without jq or base64 transports', () => {
  assert.deepEqual(api.projectGitHubData({ user: { login: 'a' }, base: { ref: 'main' }, head: { ref: 'fix' }, body: null }, 'mergeable_state'), { user: 'a', base: 'main', head: 'fix', body: '' })
  assert.equal(api.projectGitHubData({ ahead_by: 3 }, 'ahead'), 3)
  assert.deepEqual(api.projectGitHubData([{ sha: 'abcdefghi', commit: { message: 'subject\nbody', author: { name: 'A' } } }], 'full:.sha'), [{ sha: 'abcdefg', full: 'abcdefghi', msg: 'subject', author: 'A', date: '' }])
  const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
  assert.ok(!source.includes('${GH}'))
  const big = source.slice(source.indexOf('async function shBig'), source.indexOf('async function shJsonBig'))
  assert.ok(!big.includes('base64') && !big.includes('shell.exec'))
  assert.ok(!source.includes('body=@'))
})
