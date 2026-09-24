import test from 'node:test'
import assert from 'node:assert/strict'
import plugin from '../desktop/plugin.js'
import { host } from '@hermes/plugin-sdk'

function contributions() {
  const entries = []
  plugin.register({
    storage: { get: (_key, fallback) => fallback },
    register: entry => { entries.push(entry); return () => {} },
  })
  return entries
}

test('GitHub uses the native right tab group and opts into hide without disabling', () => {
  const entries = contributions()
  const pane = entries.find(entry => entry.area === 'panes')
  assert.equal(pane.title, 'GitHub')
  assert.equal(pane.data.placement, 'right')
  assert.deepEqual(pane.data.dock, { pane: 'files', pos: 'center' })
  assert.equal(pane.data.closeBehavior, 'hide')
  assert.ok(pane.data.revealAliases.includes('github'))
})

test('persistent GitHub navigation and route are registered independently of pane rendering', () => {
  const entries = contributions()
  const nav = entries.find(entry => entry.area === 'sidebar.nav')
  const route = entries.find(entry => entry.area === 'routes')
  assert.equal(nav.data.label, 'GitHub')
  assert.equal(nav.data.codicon, 'github')
  assert.equal(nav.data.path, route.data.path)
  assert.equal(typeof route.render, 'function')
  const navigation = []
  const oldNavigate = host.navigate
  host.navigate = path => navigation.push(path)
  try {
    entries.find(entry => entry.id === 'palette-page').data.run()
    assert.deepEqual(navigation, [route.data.path])
  } finally {
    host.navigate = oldNavigate
  }
})

test('reopening prefers the public SDK reveal action', () => {
  const entries = contributions()
  const reveals = []
  const oldReveal = host.revealPane
  host.revealPane = id => reveals.push(id)
  try {
    entries.find(entry => entry.id === 'palette').data.run()
    assert.deepEqual(reveals, [`${plugin.id}:pane`])
  } finally {
    host.revealPane = oldReveal
  }
})

test('titlebar toggles through the host independently of explicit Open', () => {
  const entry = contributions().find(entry => entry.id === 'titlebar-github')
  const component = entry.render()
  const button = component.type(component.props)
  const toggles = []
  const oldToggle = host.togglePane
  host.togglePane = id => toggles.push(id)
  try {
    assert.equal(button.props['aria-label'], 'GitHub')
    button.props.onClick()
    button.props.onClick()
    assert.deepEqual(toggles, ['githermes:pane', 'githermes:pane'])
  } finally { host.togglePane = oldToggle }
})

test('legacy reopening requests open rather than toggle or plugin enable', () => {
  const entries = contributions()
  const previousWindow = globalThis.window
  const previousEvent = globalThis.CustomEvent
  const events = []
  globalThis.window = { dispatchEvent: event => events.push(event) }
  globalThis.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options.detail } }
  try {
    entries.find(entry => entry.id === 'palette').data.run()
    assert.equal(events.length, 1)
    assert.equal(events[0].type, 'hermes:pane-toggle-reveal')
    assert.deepEqual(events[0].detail, { id: `${plugin.id}:pane`, mode: 'open' })
  } finally {
    globalThis.window = previousWindow
    globalThis.CustomEvent = previousEvent
  }
})
