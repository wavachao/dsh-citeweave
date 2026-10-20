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
  for (const path of ['package.json', 'index.js', 'client.js', 'cordis.patch.yml', 'README.md', 'README.zh-CN.md', 'CHANGELOG.md', 'LICENSE', 'icon.svg', 'locale/en.json', 'locale/zh.json', 'docs/backend.md', 'docs/reference.md', 'docs/images/geography.png', 'docs/images/biology.png', 'docs/images/engineering.png', 'docs/images/README.md', 'docs/images/GFDL-1.2.txt']) {
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
  assert.ok(!files.some(path => path.startsWith('backend/')), 'the Python backend belongs in the GitHub source checkout, not the DSH installation archive')
  assert.ok(!files.some(path => /(?:\.(?:py|pyc|toml|safetensors|pt|pth|bin|sqlite3?|db|pem|key|p12|pfx)|(?:^|\/)uv\.lock)$/i.test(path)), 'Python sources, dependency locks, models, databases, and credentials must not ship with the plugin')
  const rootFiles = new Set(['package.json', 'index.js', 'client.js', 'cordis.patch.yml', 'README.md', 'README.zh-CN.md', 'CHANGELOG.md', 'LICENSE', 'icon.svg'])
  assert.ok(files.every(path => rootFiles.has(path) || path.startsWith('locale/') || path.startsWith('docs/')), 'only plugin runtime resources and documentation may be published')
  for (const [name, target] of Object.entries(manifest.exports)) {
    if (!target.includes('*')) assert.ok(files.includes(target.replace(/^\.\//, '')), `export ${name} must resolve in the installation archive`)
  }
  for (const locale of ['en', 'zh']) {
    const messages = JSON.parse(await readFile(new URL(`../locale/${locale}.json`, import.meta.url), 'utf8'))
    assert.ok(messages.meta.title)
    assert.ok(messages.meta.description)
  }
})

test('GitHub source retains backend build inputs independently of the npm plugin', async () => {
  for (const path of ['pyproject.toml', 'uv.lock', 'Dockerfile', '.dockerignore', '.env.example', 'compose.yaml', 'LICENSE', 'THIRD_PARTY.md', 'src/citeweave/__main__.py', 'src/citeweave/app.py', 'src/citeweave/jobs.py', 'src/citeweave/model_runtime.py', 'scripts/download_models.py', 'scripts/download_ranker.py']) {
    const source = await readFile(new URL(`../backend/${path}`, import.meta.url), 'utf8')
    assert.ok(source.trim(), `backend/${path} must remain available in the source repository`)
  }
})
