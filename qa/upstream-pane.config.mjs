import { resolve } from 'node:path'
import { createRequire } from 'node:module'
const upstream = process.cwd()
const require = createRequire(resolve(upstream, 'package.json'))
if (!process.env.GITHERMES_SOURCE) throw new Error('Set GITHERMES_SOURCE')
export default {
  resolve: { alias: [
    { find: '@hermes/plugin-sdk', replacement: resolve(upstream, 'apps/desktop/src/sdk/index.ts') },
    { find: 'githermes-under-test', replacement: resolve(process.env.GITHERMES_SOURCE, 'desktop/plugin.js') },
    { find: /^react$/, replacement: require.resolve('react') },
    { find: 'react/jsx-runtime', replacement: require.resolve('react/jsx-runtime') },
    { find: '@hermes/shared/billing', replacement: resolve(upstream, 'apps/shared/src/billing-types.ts') },
    { find: '@hermes/shared/color', replacement: resolve(upstream, 'apps/shared/src/color.ts') },
    { find: '@hermes/shared', replacement: resolve(upstream, 'apps/shared/src') },
    { find: '@', replacement: resolve(upstream, 'apps/desktop/src') },
  ] },
  test: { environment: 'jsdom', include: ['upstream-pane.test.ts'], globals: false },
}
