import test from 'node:test'
import assert from 'node:assert/strict'
import { decodeShellPayload } from '../desktop/plugin.js'

test('shell payload decodes intact Unicode data and base64 line wrapping', () => {
  const text = JSON.stringify({ title: 'Review 日本語', id: 42 })
  const encoded = Buffer.from(text).toString('base64')
  assert.equal(decodeShellPayload(encoded.match(/.{1,12}/g).join('\n')), text)
  assert.equal(decodeShellPayload(''), '')
})

test('shell payload fails closed on redaction and truncation without repairing bytes', () => {
  for (const encoded of ['eyJh...ab12', 'YWJ', 'YWJj====', 'YW=Jj', '<redacted>']) {
    assert.throws(() => decodeShellPayload(encoded), /response altered or truncated by host/)
  }
})
