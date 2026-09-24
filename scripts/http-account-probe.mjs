// Executed by pytest against two real, authenticated Hermes HTTP servers.
import assert from 'node:assert/strict'
import { existsSync, writeFileSync } from 'node:fs'
import { host, atom } from '@hermes/plugin-sdk'
import plugin, * as api from '../desktop/plugin.js'
let input = ''; for await (const chunk of process.stdin) input += chunk
const { urls, headers, config } = JSON.parse(input)
const pause = ms => new Promise(r => setTimeout(r, ms))
let arrive, release, first = true, selectionCalls = 0
const arrived = new Promise(r => { arrive = r })
host.state.gateway = atom('open'); host.state.connectionId = atom('real-http'); host.state.profile = atom('alpha'); host.state.activeSessionId = atom('s')
plugin.register({ register() {}, onDispose() {}, storage: { get() {}, set() {} }, rest: async (path, options = {}) => {
  if (path.startsWith('/selection')) selectionCalls++
  const response = await fetch(urls[options.method ? 1 : 0] + '/api/plugins/githermes' + path, { method: options.method || 'GET', headers: { ...headers, 'Content-Type': 'application/json' }, ...(options.body ? { body: JSON.stringify(options.body) } : {}) })
  const result = await response.json()
  if (!response.ok) throw Error(String(response.status))
  if (path.startsWith('/selection') && first) { first = false; arrive(); await new Promise(r => { release = r }) }
  return result
} })
const a = api.refreshGitHubAccounts().catch(() => {})
await arrived
host.state.profile.set('beta')
const b = api.refreshGitHubAccounts()
await pause(100)
assert.equal(selectionCalls, 1, 'late A reply must serialize B selection, not create an orphan')
release(); await a; await b
const selected = api.captureGitHubScope()
assert.equal(selected.ready, true)
assert.equal(selected.login, 'alpha')
// Dispatch through the OTHER process with the UI's actual capability.
const pending = fetch(urls[0] + '/api/plugins/githermes/operation?profile=beta', { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ lease: selected.lease, epoch: selected.epoch, operation: { operation: 'issue.close', repo: 'a/b', number: 1 } }) })
try {
  for (let i = 0; i < 500 && !existsSync(config + '/arrived'); i++) await pause(10)
  assert.ok(existsSync(config + '/arrived'))
  await api.selectGitHubAccount('beta')
} finally { writeFileSync(config + '/release', '') }
assert.equal((await pending).status, 409)
assert.equal(existsSync(config + '/calls.jsonl'), false)
assert.equal(api.captureGitHubScope().lease, selected.lease)
console.log('GREEN: late A/B selection + delayed stale mutation, real middleware/fake-gh/two processes')
