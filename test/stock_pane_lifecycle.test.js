import test from 'node:test'
import assert from 'node:assert/strict'
import plugin, { createGithubPaneLifecycle } from '../desktop/plugin.js'
import { host } from '@hermes/plugin-sdk'

function fixture(saved = new Map()) {
  const entries = new Map()
  const dispose = []
  plugin.register({
    storage: { get: (k, fallback) => saved.has(k) ? saved.get(k) : fallback, set: (k, v) => saved.set(k, v) },
    onDispose: fn => dispose.push(fn),
    register: entry => { entries.set(entry.id, entry); return () => entries.delete(entry.id) },
  })
  const component = entries.get('titlebar-github').render()
  return { entries, saved, closePlugin: () => dispose.forEach(fn => fn()), click: () => component.type(component.props).props.onClick() }
}

test('stock pane provides its own Close and prevents native Close from disabling navigation', () => {
  const f = fixture()
  const pane = f.entries.get('pane')
  assert.equal(pane.data.uncloseable, true)
  function findClose(node) {
    if (!node || typeof node !== 'object') return null
    if (node.props?.['aria-label'] === 'Close GitHub pane') return node
    const children = node.props?.children
    for (const child of Array.isArray(children) ? children : [children]) {
      const found = findClose(child)
      if (found) return found
    }
    return null
  }
  const button = findClose(pane.render())
  assert.ok(button, 'a visible close action exists even when the native tab strip is hidden')
  button.props.onClick()
  assert.equal(f.entries.has('pane'), false)
  assert.ok(f.entries.has('nav-github'))
  f.closePlugin()
})

test('hidden choice survives plugin reload while page and titlebar remain registered', () => {
  const f = fixture()
  f.click()
  f.closePlugin()
  const reloaded = fixture(f.saved)
  assert.equal(reloaded.entries.has('pane'), false)
  assert.ok(reloaded.entries.has('nav-github'))
  reloaded.entries.get('palette').data.run()
  assert.ok(reloaded.entries.has('pane'))
  reloaded.closePlugin()
})

test('a pane behind Files is revealed before the next toggle closes it', () => {
  let visible = false
  host.paneVisibility = () => ({ get: () => visible })
  host.revealPane = () => { visible = true }
  const f = fixture()
  f.click()
  assert.equal(visible, true)
  assert.ok(f.entries.has('pane'))
  f.click()
  assert.equal(f.entries.has('pane'), false)
  f.closePlugin()
  delete host.paneVisibility
  delete host.revealPane
})

test('disposed lifecycle cannot register or change the persisted user choice', () => {
  let registrations = 0
  let cleanup
  let saved = false
  const lifecycle = createGithubPaneLifecycle({
    register: () => { registrations++; return () => {} },
    onDispose: fn => { cleanup = fn },
    storage: { get: () => saved, set: (_key, value) => { saved = value } },
  }, { id: 'pane' }, { revealPane() {} })
  cleanup()
  lifecycle.open(); lifecycle.close(); lifecycle.toggle()
  assert.equal(registrations, 1)
  assert.equal(saved, false)
})

test('stock SDK titlebar closes only the registered pane and reopens it', () => {
  const reveals = []
  host.revealPane = id => reveals.push(id)
  host.paneVisibility = () => ({ get: () => true })
  delete host.togglePane
  const f = fixture()
  assert.ok(f.entries.has('pane'))
  f.click()
  assert.equal(f.entries.has('pane'), false, 'visible GitHub must close, not reveal again')
  assert.ok(f.entries.has('nav-github'))
  assert.ok(f.entries.has('route-github'))
  f.click()
  assert.ok(f.entries.has('pane'))
  assert.deepEqual(reveals, ['githermes:pane'])
  assert.deepEqual(f.entries.get('pane').data.dock, { pane: 'files', pos: 'center' })
  f.closePlugin()
  delete host.revealPane
  delete host.paneVisibility
})
