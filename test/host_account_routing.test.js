import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync, mkdirSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { execFileSync } from 'node:child_process'
import { runInNewContext } from 'node:vm'

const sourceRoot = process.env.HERMES_SOURCE_DIR
const dependencies = process.env.HERMES_QUERY_ROOT

test('real Desktop route planner: narrow companion patch co-locates all GitHermes leases and commands', { skip: !sourceRoot || !dependencies ? 'Set HERMES_SOURCE_DIR and HERMES_QUERY_ROOT for real host routing test' : false }, async () => {
  const require = createRequire(import.meta.url)
  const esbuild = require(require.resolve('esbuild', { paths: [dependencies] }))
  const relative = 'apps/desktop/electron/connection-config.ts'
  let original = readFileSync(join(sourceRoot, relative), 'utf8')
  const scratch = mkdtempSync(join(process.env.TMPDIR, 'githermes-routing-'))
  try {
    mkdirSync(dirname(join(scratch, relative)), { recursive: true })
    writeFileSync(join(scratch, relative), original)
    const patchFile = new URL('../integration/hermes-profile-routing.patch', import.meta.url).pathname
    let patched
    try {
      execFileSync('git', ['apply', patchFile], { cwd: scratch, stdio: 'pipe' })
      patched = readFileSync(join(scratch, relative), 'utf8')
    } catch {
      // Also verify against an already-patched gateway checkout.
      execFileSync('git', ['apply', '--reverse', patchFile], { cwd: scratch, stdio: 'pipe' })
      patched = original
      original = readFileSync(join(scratch, relative), 'utf8')
    }
    async function load(source) {
      const bundle = await esbuild.build({ stdin: { contents: source, loader: 'ts', resolveDir: dirname(join(sourceRoot, relative)) }, bundle: true, platform: 'node', format: 'cjs', write: false })
      const module = { exports: {} }
      runInNewContext(bundle.outputFiles[0].text, { module, exports: module.exports, require, process, URL, setTimeout, clearTimeout, console })
      return module.exports
    }
    const before = await load(original), after = await load(patched)
    const options = { primaryProfile: 'default', globalRemote: false, profileRemoteOverride: false, requestMethod: 'POST', requestPath: '/api/plugins/githermes/operation?profile=ebi' }
    assert.equal(before.unscopableMutatingRequest(options), true, 'baseline must reproduce the pooled-POST routing gap')
    for (const [method, route] of [['GET', 'accounts'], ['POST', 'selection'], ['POST', 'revoke'], ['POST', 'operation']]) {
      const opts = { ...options, requestMethod: method, requestPath: '/api/plugins/githermes/' + route + '?profile=ebi' }
      const routePlan = after.resolveProfileBackendRoute('ebi', opts)
      assert.equal(routePlan.backend, 'primary')
      assert.equal(routePlan.descriptorProfile, 'ebi')
      assert.equal(routePlan.scopePath, true)
    }
    assert.equal(after.unscopableMutatingRequest({ ...options, requestPath: '/api/plugins/unrelated/operation' }), true)
    assert.equal(after.unscopableMutatingRequest({ ...options, requestPath: '/api/plugins/githermes/unknown' }), true)
  } finally { rmSync(scratch, { recursive: true, force: true }) }
})
