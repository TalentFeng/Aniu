import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

test('login view includes a remember-password risk reminder and clear action', () => {
  const source = readFileSync(new URL('../src/views/LoginView.vue', import.meta.url), 'utf-8')

  assert.match(source, /记住密码会将密码保存在当前浏览器中/)
  assert.match(source, /清除已记住密码/)
})
