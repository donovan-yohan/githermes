// Run via qa/upstream-pane.config.mjs in an isolated, dependency-installed official tree.
import { beforeAll, expect, it } from 'vitest'
import { act, render } from '@testing-library/react'
import { createElement } from 'react'
import { host } from '@hermes/plugin-sdk'
import { createGithubPaneLifecycle } from 'githermes-under-test'
import { createPluginContext } from '@/contrib/plugin'
import { registry } from '@/contrib/registry'
import { TreeGroup } from '@/components/pane-shell/tree/renderer/tree-group'
import { group, split } from '@/components/pane-shell/tree/model'
import { $layoutTree, $collapsedTreeSides, setTreeSideCollapsed } from '@/components/pane-shell/tree/store'

beforeAll(() => {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as any
  globalThis.CSS = { ...globalThis.CSS, escape: (s: string) => s }
  HTMLElement.prototype.scrollIntoView = () => {}
})

function fixture() {
  const cleanups: (() => void)[] = []
  const ctx = createPluginContext('githermes', fn => cleanups.push(fn))
  ctx.storage.remove('paneHidden')
  const workspace = registry.register({ id: 'workspace', area: 'panes', data: { placement: 'main', uncloseable: true } })
  const files = registry.register({ id: 'files', area: 'panes', data: { placement: 'right' }, render: () => createElement('div', { 'data-files': true }, 'Files') })
  ctx.register({ id: 'nav', area: 'sidebar.nav' })
  $layoutTree.set(split('row', [group(['workspace'], { id: 'main' }), group(['files'], { id: 'right' })]))
  const controller = createGithubPaneLifecycle(ctx, {
    id: 'pane', area: 'panes', title: 'GitHub',
    data: { placement: 'right', uncloseable: true, dock: { pane: 'files', pos: 'center' } },
    render: () => createElement('div', { 'data-github': true }, 'GitHub'),
  }, host)
  controller.open()
  return { ctx, controller, cleanup: () => { cleanups.forEach(fn => fn()); workspace(); files() } }
}

it('real SDK and native Files tabs survive close/reopen without losing navigation or placement', () => {
  const f = fixture()
  const tree = $layoutTree.get()!
  const view = render(createElement(TreeGroup, { node: tree.type === 'split' ? tree.children[1] as any : tree, parentAxis: 'row' }))
  const tab = () => view.container.querySelector('[data-tree-tab="githermes:pane"]')
  try {
    expect(tab()).not.toBeNull()
    expect(tab()!.querySelector('button[aria-label]')).toBeNull()
    for (let i = 0; i < 2; i++) {
      act(() => f.controller.toggle())
      expect(tab()).toBeNull()
      expect(view.container.querySelector('[data-files]')).not.toBeNull()
      expect(registry.getArea('sidebar.nav').some(c => c.id === 'githermes:nav')).toBe(true)
      expect(f.ctx.storage.get('paneHidden', false)).toBe(true)
      expect($layoutTree.get()).toBe(tree)
      act(() => f.controller.toggle())
      expect(tab()).not.toBeNull()
      expect($layoutTree.get()).toEqual(tree)
    }
  } finally { view.unmount(); f.cleanup() }
})

it('documents upstream collapse gap; explicit public Open restores the collapsed side', () => {
  expect((host as any).togglePane).toBeUndefined()
  expect((host as any).actions).toBeUndefined()
  expect((host as any).commands).toBeUndefined()
  const f = fixture()
  try {
    setTreeSideCollapsed('right', true)
    expect($collapsedTreeSides.get().has('right')).toBe(true)
    // The public SDK omits collapsed-side state. Do not pretend native toggle parity.
    expect(host.paneVisibility('githermes:pane').get()).toBe(true)
    f.controller.open()
    expect($collapsedTreeSides.get().has('right')).toBe(false)
  } finally { f.cleanup() }
})
