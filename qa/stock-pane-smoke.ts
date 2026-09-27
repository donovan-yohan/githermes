// Copy beside the unmodified upstream apps/desktop/e2e fixtures after building it.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { test, expect, type ElectronApplication, type Page, type Locator } from '@playwright/test'
import { createSandbox, buildAppEnv, launchDesktop } from './e2e/fixtures.ts'
import { writeMockProviderConfig, writeEnvFile } from '../../tests-js/scripts/mock-provider-config.ts'

test('public SDK pane lifecycle without disabling GitHermes', async () => {
  test.setTimeout(120000)
  const source = process.env.GITHERMES_SOURCE!
  if (!source) throw new Error('Set GITHERMES_SOURCE to the plugin worktree')
  const repo = path.resolve('../..')
  const out = path.resolve(process.env.GITHERMES_EVIDENCE || path.join(repo, 'stock-pane-evidence'))
  fs.mkdirSync(out, { recursive: true })
  const sandbox = createSandbox('githermes-stock')
  const home = path.join(sandbox.root, 'os-home')
  const gh = path.join(home, '.config/gh')
  const project = path.join(sandbox.root, 'project')
  for (const p of [home, gh, project]) fs.mkdirSync(p, { recursive: true })
  execFileSync('git', ['init', '--initial-branch=fixture', project], { stdio: 'ignore' })
  // Exercise disk loading with the real SDK. No GitHub backend/account fixture:
  // account transport is deliberately outside this pane-only acceptance test.
  fs.cpSync(path.join(source, 'desktop'), path.join(sandbox.hermesHome, 'desktop-plugins/githermes'), { recursive: true })
  writeMockProviderConfig(sandbox.hermesHome, 'http://127.0.0.1:1')
  writeEnvFile(sandbox.hermesHome)
  const env = buildAppEnv(sandbox, {
    HOME: home, XDG_CONFIG_HOME: path.join(home, '.config'), XDG_CACHE_HOME: path.join(home, '.cache'),
    HERMES_REAL_HOME: home, GH_CONFIG_DIR: gh, TERMINAL_HOME_MODE: 'profile', SHELL: '/bin/false',
    TEST_WORKER_INDEX: '0', PYTHONDONTWRITEBYTECODE: '1',
  })
  for (const k of ['HERMES_DESKTOP_DEV_SERVER', 'HERMES_DESKTOP_HERMES', 'GH_DEBUG', 'GH_HOST']) delete env[k]
  const seed = 'import sys; from hermes_state import SessionDB; db=SessionDB(); db.create_session("pane-fixture",source="desktop",cwd=sys.argv[1]); db.append_message("pane-fixture","user","Pane fixture session"); db.append_message("pane-fixture","assistant","Synthetic fixture only"); db.close()'
  execFileSync(path.join(repo, '.venv/bin/python'), ['-c', seed, project], { cwd: repo, env })
  const errors: string[] = []
  const checkpoints: object[] = []
  let app: ElectronApplication | undefined, page: Page | undefined
  try {
    ;({ app, page } = await launchDesktop(env))
    page.on('pageerror', e => errors.push(e.message))
    await page.getByText('Pane fixture session', { exact: true }).first().click({ timeout: 60000 })
    const icon = page.locator('button[aria-label="GitHub"]').first()
    const nav = page.getByRole('listitem').getByRole('button', { name: 'GitHub', exact: true })
    const close = page.getByRole('button', { name: 'Close GitHub pane', exact: true })
    const tab = page.locator('[data-tree-tab="githermes:pane"]')
    const files = page.locator('[data-tree-tab="files"]')
    const decisions = () => page!.evaluate(() => localStorage.getItem('hermes.desktop.pluginDecisions.v2'))
    const hidden = () => page!.evaluate(() => localStorage.getItem('hermes.plugin.githermes.paneHidden'))
    const checkpoint = async (name: string) => {
      checkpoints.push({ name, closeVisible: await close.isVisible(), hidden: await hidden(), decisions: await decisions() })
      await page!.screenshot({ path: path.join(out, `${name}.png`) })
    }
    await expect(icon).toBeVisible()
    await expect(nav).toBeVisible()
    const enabledBefore = await decisions()
    // Public palette Open establishes visible state regardless of initial sidebar state.
    await page.keyboard.press('Control+k')
    await page.getByRole('combobox').fill('Open GitHub pane')
    const option = page.getByRole('option', { name: /Open GitHub pane/ })
    await expect(option).toBeVisible()
    await page.keyboard.press('ArrowDown')
    await expect(option).toHaveAttribute('aria-selected', 'true')
    await page.keyboard.press('Enter')
    await expect(close).toBeVisible()
    await checkpoint('opened')
    for (const name of ['closed', 'reopened', 'closed-again']) {
      await icon.click()
      if (name === 'reopened') await expect(close).toBeVisible()
      else await expect(close).toBeHidden()
      await expect(nav).toBeVisible()
      expect(await decisions()).toBe(enabledBefore)
      await checkpoint(name)
    }
    await icon.click()
    await expect(close).toBeVisible()
    await close.click()
    await expect(close).toBeHidden()
    await expect(nav).toBeVisible()
    expect(await decisions()).toBe(enabledBefore)
    await checkpoint('close-control')
    await icon.click()
    await expect(close).toBeVisible()
    await checkpoint('icon-reopened')
    // Expose the Files contribution using the native shortcut, not a tree reset.
    await page.keyboard.press('Control+j')
    await expect(files).toBeVisible()
    await expect(tab).toBeVisible()
    const groupOf = (loc: Locator) => loc.evaluate(e => e.closest('[data-tree-group]')?.getAttribute('data-tree-group'))
    expect(await groupOf(tab)).toBe(await groupOf(files))
    await files.click()
    await expect(tab).toHaveAttribute('aria-selected', 'false')
    await icon.click()
    await expect(tab).toHaveAttribute('aria-selected', 'true')
    const group = await groupOf(tab)
    await checkpoint('files-group')
    await icon.click()
    await expect(tab).toBeHidden()
    // Auto hides a lone Files tab strip; its actual content must survive.
    await expect(page.getByRole('button', { name: 'Refresh tree', exact: true })).toBeVisible()
    await icon.click()
    await expect(tab).toBeVisible()
    expect(await groupOf(tab)).toBe(group)
    expect(await tab.locator('button[aria-label]').count()).toBe(0)
    await close.click()
    await page.reload()
    await expect(icon).toBeVisible()
    await expect(close).toBeHidden()
    await expect(nav).toBeVisible()
    expect(await decisions()).toBe(enabledBefore)
    expect(await hidden()).toBe('true')
    await checkpoint('closed-after-reload')
    await icon.click()
    await expect(close).toBeVisible()
    await expect(tab).toBeVisible()
    expect(await groupOf(tab)).toBe(group)
    expect(await decisions()).toBe(enabledBefore)
    await checkpoint('reopened-after-reload')
    // Characterize, do NOT conceal, the official SDK's side-collapse gap.
    await page.getByRole('button', { name: 'Hide right sidebar', exact: true }).click()
    // Native sidebar toggle first restores a minimized sibling (e.g. Terminal).
    // If so, a second native press performs the actual side collapse.
    if (await close.isVisible()) {
      await page.getByRole('button', { name: 'Hide right sidebar', exact: true }).click()
    }
    await expect(close).toBeHidden()
    await icon.click()
    await expect(close).toBeHidden()
    expect(await hidden()).toBe('true')
    await checkpoint('collapsed-first-press-limitation')
    await icon.click()
    await expect(close).toBeVisible()
    await expect(nav).toBeVisible()
    expect(await decisions()).toBe(enabledBefore)
    await checkpoint('collapsed-second-press-reopens')
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify({ upstream: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(), platform: process.platform, checkpoints }, null, 2))
  } finally {
    if (page) {
      fs.writeFileSync(path.join(out, 'final.html'), await page.content())
      fs.writeFileSync(path.join(out, 'storage.json'), JSON.stringify(await page.evaluate(() => ({ ...localStorage })), null, 2))
      await page.screenshot({ path: path.join(out, 'final.png') })
    }
    fs.writeFileSync(path.join(out, 'pageerrors.json'), JSON.stringify(errors, null, 2))
    fs.writeFileSync(path.join(out, 'sandbox.txt'), sandbox.root)
    if (app) await app.close()
  }
})
