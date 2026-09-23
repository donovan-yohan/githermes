import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { host, atom } from '@hermes/plugin-sdk'
import * as api from '../desktop/plugin.js'

// Resolve a real, already installed desktop dependency; never replace shared installs.
const require = createRequire(import.meta.url)
let queryPath
try {
  queryPath = require.resolve('@tanstack/react-query', { paths: [process.env.HERMES_QUERY_ROOT || process.cwd()] })
} catch (error) {
  if (process.env.HERMES_QUERY_ROOT) throw error // An explicitly requested real-query run must not silently skip.
}
// QueryObserver intentionally disables timers on the server. Set browser mode before import.
globalThis.window = {}
const realQuery = queryPath ? require(queryPath) : null
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve() }

test('PR polling stops after errors and explicit refresh remains available', () => {
  const opts = api.inboxQueryOptions({}, 'test', true, 'open')
  assert.equal(opts.refetchInterval({ state: { status: 'success' } }), 60_000)
  assert.equal(opts.refetchInterval({ state: { status: 'error' } }), false)
  assert.equal(opts.retry, false)
})

function renderedOptions(active = true, gateway = 'open') {
  host.state.gateway = atom(gateway)
  host.state.connectionId = atom('refresh-test')
  host.state.profile = atom('test')
  host.state.activeSessionId = atom('session')
  let options
  globalThis.__ghTestQuery = value => { options = value; return { data: undefined } }
  try { api.GitHubInbox({ active }) } finally { delete globalThis.__ghTestQuery }
  return options
}

test('real QueryClient: stale inbox refreshes on focus, never hidden or disconnected', { skip: !realQuery && 'Set HERMES_QUERY_ROOT to an existing desktop dependency root' }, async t => {
  t.mock.timers.enable({ apis: ['Date', 'setTimeout', 'setInterval'], now: 1_000_000 })
  const { QueryClient, QueryObserver, focusManager } = realQuery
  const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
  client.mount()
  focusManager.setFocused(true)
  let calls = 0
  const options = (active = true, gateway = 'open') => ({ ...renderedOptions(active, gateway), queryFn: async () => { calls++; return { kind: 'pulls', items: [] } } })
  const observer = new QueryObserver(client, options())
  const unsubscribe = observer.subscribe(() => {})
  try {
    await flush()
    assert.equal(calls, 1)
    focusManager.setFocused(false)
    t.mock.timers.tick(60_001); await flush()
    assert.equal(calls, 1)
    focusManager.setFocused(true); await flush()
    assert.equal(calls, 2, 'stale open inbox must refresh on focus')
    for (const [active, gateway] of [[false, 'open'], [true, 'closed']]) {
      observer.setOptions(options(active, gateway))
      focusManager.setFocused(false)
      t.mock.timers.tick(180_000); await flush()
      focusManager.setFocused(true); await flush()
      assert.equal(calls, 2)
    }
  } finally {
    unsubscribe(); client.unmount(); client.clear(); focusManager.setFocused(undefined)
    t.mock.timers.reset()
  }
})

test('real QueryObserver: live reviews poll at 60s and pause for pane/window/gateway/unmount', { skip: !realQuery && 'Set HERMES_QUERY_ROOT to an existing desktop dependency root' }, async t => {
  t.mock.timers.enable({ apis: ['Date', 'setTimeout', 'setInterval'], now: 1_000_000 })
  const { QueryClient, QueryObserver, focusManager } = realQuery
  const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
  client.mount(); focusManager.setFocused(true)
  let calls = 0
  const options = (active = true, gateway = 'open') => ({
    ...api.inboxQueryOptions({ view: 'reviews' }, 'test', active, gateway),
    queryFn: async () => ({ kind: 'reviews', items: [{ id: ++calls }] }),
  })
  const observer = new QueryObserver(client, options())
  const unsubscribe = observer.subscribe(() => {})
  const advance = async ms => { t.mock.timers.tick(ms); await flush() }
  try {
    await flush(); assert.equal(calls, 1)
    await advance(59_999); assert.equal(calls, 1)
    await advance(1); assert.equal(calls, 2, 'open review queue must poll without focus changes')
    assert.equal(observer.getCurrentResult().data.items[0].id, 2)
    observer.setOptions(options(false)); await advance(180_000); assert.equal(calls, 2)
    observer.setOptions(options(true, 'closed')); await advance(180_000); assert.equal(calls, 2)
    observer.setOptions(options()); await flush(); assert.equal(calls, 3, 'reconnected stale queue refreshes')
    focusManager.setFocused(false); await advance(180_000); assert.equal(calls, 3)
    focusManager.setFocused(true); await flush(); assert.equal(calls, 4)
    await advance(60_000); assert.equal(calls, 5)
    unsubscribe(); await advance(180_000); assert.equal(calls, 5)
  } finally {
    unsubscribe(); client.unmount(); client.clear(); focusManager.setFocused(undefined)
    t.mock.timers.reset()
  }
})
