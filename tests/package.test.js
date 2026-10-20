import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { pack } from '../scripts/package.js'

test('distributable contains the complete plugin and only public runtime resources', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-citeweave-package-'))
  t.after(() => rm(directory, { recursive: true, force: true }))
  const manifest = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))
  const archive = await pack(directory)
  const files = archive.files.map(file => file.path)
  assert.equal(archive.name, 'dsh-citeweave')
  assert.equal(archive.version, manifest.version)
  for (const path of ['package.json', 'index.js', 'client.js', 'cordis.patch.yml', 'README.md', 'README.zh-CN.md', 'CHANGELOG.md', 'LICENSE', 'icon.svg', 'locale/en.json', 'locale/zh.json']) {
    assert.ok(files.includes(path), `${path} must ship in the installation archive`)
  }
  assert.equal(manifest.type, 'module')
  assert.equal(manifest.dsh.bundle.patch, './cordis.patch.yml')
  assert.equal(manifest.dsh.client.platform, 'web')
  assert.equal(manifest.exports['./client'], './client.js')
  assert.equal(manifest.license, 'MIT')
  assert.ok(manifest.repository.url.includes('wavachao/dsh-citeweave'))
  assert.ok(manifest.engines.dsh.includes('0.2.1-rc.2'))
  assert.ok(files.every(path => !/(^|\/)(node_modules|\.git|\.env|tests|scripts|work|\.github)(\/|$)/.test(path)), files.join('\n'))
  for (const locale of ['en', 'zh']) {
    const messages = JSON.parse(await readFile(new URL(`../locale/${locale}.json`, import.meta.url), 'utf8'))
    assert.ok(messages.meta.title)
    assert.ok(messages.meta.description)
  }
})
