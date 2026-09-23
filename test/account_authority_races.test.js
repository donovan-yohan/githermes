import test from 'node:test'
import assert from 'node:assert/strict'
import { host, atom } from '@hermes/plugin-sdk'
import plugin, * as api from '../desktop/plugin.js'

const tick = async () => { for (let i = 0; i < 60; i++) await Promise.resolve() }
let count = 0
function setup() {
  host.state.gateway = atom('open'); host.state.connectionId = atom('race-' + ++count); host.state.profile = atom('A'); host.state.activeSessionId = atom('s')
  const leases = new Map(), calls = []
  let release, arrived, block = true, network = false, loseResponse = false
  const arrival = new Promise(r => { arrived = r })
  plugin.register({ register() {}, onDispose() {}, storage: { get() {}, set() {} }, rest: async (path, { body } = {}) => {
    calls.push(path)
    if (network) throw Error('network uncertainty')
    if (path.startsWith('/accounts')) return { accounts: [{ login: 'alpha', active: true }, { login: 'beta' }], backend: 'shared' }
    if (path.startsWith('/revoke')) {
      let lease = leases.get(body.lease)
      if (!lease) lease = { lease: body.lease, epoch: 100, reset: true }
      lease = { ...lease, epoch: lease.epoch + 1, login: null }
      leases.set(lease.lease, lease)
      return { ...lease }
    }
    if (path.startsWith('/selection')) {
      let lease = leases.get(body.lease)
      if (lease) assert.equal(lease.epoch, body.epoch)
      lease = { lease: body.lease || 'L' + leases.size, epoch: (lease?.epoch || 0) + 1, login: body.login, backend: 'shared' }
      leases.set(lease.lease, lease)
      if (block) { block = false; arrived(); await new Promise(r => { release = r }) }
      if (loseResponse) { loseResponse = false; throw Error('lost selection reply') }
      return { ...lease }
    }
    assert.fail('unexpected operation')
  } })
  return { leases, calls, arrival, lose: () => { loseResponse = true }, release: () => release(), network: value => { network = value } }
}

test('late A selection cannot replace B authority or leave an orphan active', async () => {
  const f = setup()
  const a = api.refreshGitHubAccounts().catch(e => e)
  await f.arrival
  host.state.profile.set('B'); await tick()
  const b = api.refreshGitHubAccounts()
  await tick()
  assert.equal(f.calls.filter(p => p.startsWith('/selection')).length, 1, 'same-connection selection must serialize')
  f.release(); await a; await b
  await api.selectGitHubAccount('beta')
  const current = api.captureGitHubScope()
  assert.equal(current.ready, true)
  assert.equal(current.login, 'beta')
  assert.deepEqual([...f.leases.values()].filter(l => l.login).map(l => l.lease), [current.lease])
})

test('lost first selection reply is revoked using the stable client capability', async () => {
  const f = setup(); f.lose()
  const first = api.refreshGitHubAccounts(); await f.arrival; f.release()
  await assert.rejects(first, /lost selection reply/)
  assert.equal(api.captureGitHubScope().ready, false)
  await api.refreshGitHubAccounts(true)
  assert.equal(api.captureGitHubScope().ready, true)
  assert.equal(f.leases.size, 1, 'no orphan may survive a lost first reply')
  assert.ok(f.calls.some(p => p.startsWith('/revoke')))
})

test('unknown authority recovery discovers again; network uncertainty does not', async () => {
  const f = setup()
  const first = api.refreshGitHubAccounts(); await f.arrival; f.release(); await first
  f.leases.clear()
  await api.refreshGitHubAccounts(true)
  assert.equal(api.captureGitHubScope().ready, true)
  f.network(true)
  const before = f.calls.filter(p => p.startsWith('/accounts')).length
  await assert.rejects(api.refreshGitHubAccounts(true), /network uncertainty/)
  assert.equal(api.captureGitHubScope().ready, false)
  assert.equal(f.calls.filter(p => p.startsWith('/accounts')).length, before)
  f.network(false)
  await api.refreshGitHubAccounts(true)
  assert.equal(api.captureGitHubScope().ready, true)
})
