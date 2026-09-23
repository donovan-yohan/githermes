import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const section = (start, end) => source.slice(source.indexOf(start), source.indexOf(end))
// Render-contract tests: JSX records component identity/props, not fake DOM or
// CSS. The actual SDK is owned by Desktop; these tests do not prove pixel parity.
const jsx = (type, props) => ({ type, props })
const sdk = Object.fromEntries(['Badge', 'StatusDot', 'Codicon', 'EmptyState', 'Button', 'Popover', 'PopoverTrigger', 'PopoverContent', 'Input'].map(name => [name, Symbol(name)]))
function evaluate(code, expression, extra = {}) {
  return vm.runInNewContext(`${code}\n${expression}`, { ...sdk, jsx, jsxs: jsx, ...extra })
}
const stateCode = section('function StateDot(', 'function TitlebarGithubButton(')

test('state indicators delegate semantic tone and geometry to SDK StatusDot', () => {
  for (const [state, isDraft, tone] of [['OPEN', false, 'good'], ['closed', false, 'bad'], ['OPEN', true, 'muted'], ['UNKNOWN', false, 'warn']]) {
    const node = evaluate(stateCode, 'StateDot(input)', { input: { state, isDraft } })
    assert.equal(node.type, sdk.StatusDot)
    assert.equal(node.props.tone, tone)
    assert.equal(node.props.style, undefined)
  }
})

test('PR state and CI/review metadata use real Badge variants and StatusDot', () => {
  for (const [key, variant, label] of [['open', 'default', 'Open'], ['closed', 'destructive', 'Closed'], ['draft', 'muted', 'Draft'], ['merged', 'default', 'Merged']]) {
    const node = evaluate(stateCode, 'StatePill({ d: {} })', { prStateKey: () => key })
    assert.equal(node.type, sdk.Badge)
    assert.equal(node.props.variant, variant)
    assert.equal(node.props.children[1], label)
    assert.equal(node.props.style, undefined)
  }
  const node = evaluate(stateCode, 'StatusDots({ pr: {} })', { ciState: () => 'failing', reviewState: () => 'approved' })
  assert.equal(node.props.children[0].type, sdk.Badge)
  assert.equal(node.props.children[0].props.children[0].type, sdk.StatusDot)
  assert.equal(node.props.children[0].props.children[0].props.tone, 'bad')
  assert.equal(node.props.children[1].props.children[0].props.tone, 'good')
})

test('label badges keep keyboard-native filter actions without repository color overrides', () => {
  const code = section('function LabelChip(', 'function setListFilter(')
  let clicks = 0
  const node = evaluate(code, 'LabelChip(input)', { input: { label: { name: 'bug', color: 'ffffff' }, onClick: () => clicks++ } })
  assert.equal(node.type, sdk.Badge)
  assert.equal(node.props.variant, 'muted')
  assert.equal(node.props.asChild, true)
  assert.equal(node.props.children.type, 'button')
  assert.equal(node.props.children.props.type, 'button')
  node.props.children.props.onClick()
  assert.equal(clicks, 1)
  assert.equal(node.props.style, undefined)
  const passive = evaluate(code, "LabelChip({ label: { name: 'bug' } })")
  assert.equal(passive.props.asChild, false)
  assert.equal(passive.props.children, 'bug')
})

test('empty results use SDK EmptyState and retain recovery actions', () => {
  const code = section('function ListEmptyState(', 'function ListMoreFooter(')
  let cleared
  const node = evaluate(code, "ListEmptyState({ kind: 'prs', state: 'open', repo: 'owner/repo', query: 'missing' })", {
    $listQuery: { set: value => { cleared = value } }, $tab: { set() {} }, openExternal() {},
  })
  assert.equal(node.props.children[0].type, sdk.EmptyState)
  assert.equal(node.props.children[0].props.title, 'No matching results')
  const clear = node.props.children[1].props.children[0]
  assert.equal(clear.type, sdk.Button)
  clear.props.onClick()
  assert.equal(cleared, '')
})

test('repository picker composes PopoverTrigger with an SDK Button', () => {
  const code = section('function RepoPicker(', 'export function labelTextColor(')
  const node = evaluate(code, "RepoPicker({ repos: ['owner/repo'], value: 'owner/repo', onChange() {} })", {
    useState: value => [value, () => {}], useRef: value => ({ current: value }), useEffect() {},
    repoOk: () => false, RepoLabel: Symbol('RepoLabel'),
  })
  const trigger = node.props.children[0].props.children[0]
  assert.equal(trigger.type, sdk.PopoverTrigger)
  assert.equal(trigger.props.asChild, true)
  assert.equal(trigger.props.children.type, sdk.Button)
  assert.equal(trigger.props.children.props.variant, 'secondary')
  assert.equal(trigger.props.children.props['aria-label'], 'Select repository')
})

test('native styles remain flat, themed and do not override segmented-control internals', () => {
  const css = section('const PANE_WRAP_CSS', '// Shell-quotes')
  assert.doesNotMatch(css, /radial-gradient|border-radius: 999px|gh-empty-icon|gh-status-chip/)
  assert.match(css, /--chrome-action-hover/)
  assert.doesNotMatch(css, /gh-(?:detail|list)-tabs\s+(?:button|>\s*div)/)
  assert.match(css, /\.gh-list-row \{\s*border: 0;/)
  assert.doesNotMatch(source, /jsx\(Badge, \{ variant: 'secondary'/)
  assert.match(source, /jsx\(Checkbox, \{\s*checked: deleteBranch,\s*onCheckedChange: checked => setDeleteBranch\(checked === true\)/)
  assert.doesNotMatch(source, /type: 'checkbox'/)
})
