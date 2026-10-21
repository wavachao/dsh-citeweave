import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { once } from 'node:events'
import { test } from 'node:test'
import { Context } from '@deepseek-ai/cordis'
import { ToolRuntime, renderToolsSdk } from '@deepseek-ai/dsh-tools'
import { projectImagesForTextModel } from '@deepseek-ai/dsh-llm'
import { SystemPrompt } from '@deepseek-ai/dsh-system-prompt'
import * as plugin from './index.js'

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=', 'base64')
const attachment = { attachmentId: 'test-image', mediaType: 'image/png', bytes: png.length, width: 1, height: 1, name: 'citeweave-i1' }

test('native tool registry: authenticated evidence, durable images, partial failures, errors, cancellation', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'citeweave test '))
  const requests = []
  let slowStarted
  const started = new Promise(resolve => { slowStarted = resolve })
  const server = createServer(async (req, res) => {
    let body = ''
    for await (const chunk of req) body += chunk
    requests.push({ path: req.url, authorization: req.headers.authorization, body: body && JSON.parse(body) })
    if (req.headers.authorization !== 'Bearer test-secret') { res.writeHead(401).end(); return }
    if (req.url === '/cache/denied.png') { res.writeHead(401).end(); return }
    if (req.url === '/cache/test.png') { res.setHeader('Content-Type', 'image/png'); res.end(png); return }
    const args = JSON.parse(body)
    if (args.query === 'slow') { slowStarted(); return }
    if (args.query === 'malformed') { res.setHeader('Content-Type', 'application/json'); res.end('{"query":"malformed","sources":"invalid","images":[]}'); return }
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify({
      query: args.query,
      sources: [{ id: 's1', title: 'A [diagram]', url: 'https://example.org/%E7%8B%AE%E5%AD%90?q=1&lang=en&name=a%20b', text: 'Factual page text.' }],
      images: args.query === 'empty' ? [] : [
        { id: 'i1', source_id: 's1', url: 'https://example.org/original.png', render_url: args.query === 'denied-image' ? '/cache/denied.png' : '/cache/test.png', source_url: 'https://example.org/page?q=1', caption: 'A [diagram]', caption_kind: 'visual_description' },
        { id: 'i2', source_id: 's1', url: 'https://example.org/bad.png', render_url: 'https://untrusted.invalid/cache/leak', source_url: 'https://example.org/page', caption: 'Unusable' },
      ],
      retrieval_errors: [{ url: 'https://example.org/missing', error: 'fetch failed' }],
    }))
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const endpoint = `http://127.0.0.1:${server.address().port}`
  const ctx = new Context()
  t.after(async () => {
    await ctx.fiber.dispose()
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
    await rm(directory, { recursive: true, force: true })
  })
  // Test the plugin through real Cordis and the real native ToolRuntime. Storage
  // is a tiny byte-preserving provider; production uses Harness attachment-local.
  ctx.provide('attachments', {
    async saveImage(input) {
      assert.equal(input.mediaType, 'image/png')
      await writeFile(join(directory, 'image.png'), input.data)
      return attachment
    },
    imageHostPath() { return join(directory, 'image.png') },
  })
  ctx.provide('fs', { processPathFromHostPath: path => path })
  await ctx.plugin(SystemPrompt, { includeRuntimeContext: false }).await()
  await ctx.plugin(ToolRuntime).await()
  const fiber = ctx.plugin(plugin, { endpoint, accessToken: 'test-secret' })
  await fiber.await()
  assert.ok(ctx.tools.get('citeweave_search'))
  assert.ok((await ctx.systemPrompt.assemble()).sections.some(section => section.name === 'tool:citeweave_search'))
  const call = (args, signal = new AbortController().signal) => ctx.tools.execute({ name: 'citeweave_search', arguments: args, callId: `test-${requests.length}`, signal })

  const result = await call({ query: ' diagram ', urls: ['https://example.org/page'] })
  assert.equal(result.isError, false, JSON.stringify(result))
  assert.equal(result.value.images.length, 1)
  assert.equal(result.value.images[0].id, 'i1')
  assert.equal(result.value.images[0].source_id, 's1')
  assert.deepEqual(result.value.images[0].attachment, attachment)
  assert.deepEqual(result.content[1], { type: 'image', attachment })
  // This is Harness's native provider-boundary projection: stored content keeps
  // images, while declared text-only models receive text and the embed Markdown.
  const projected = projectImagesForTextModel([{ role: 'tool', content: result.content }])
  assert.ok(projected[0].content.every(block => block.type === 'text'))
  assert.match(projected[0].content[0].text, /!\[A/)
  assert.equal(result.content[1].type, 'image')
  const definition = ctx.tools.get('citeweave_search')
  assert.equal(definition.isConcurrencySafe({ query: 'diagram' }), false)
  assert.equal(definition.output.schema.properties.sources.items.properties.url.type, 'string')
  assert.equal(definition.output.schema.properties.images.items.properties.attachment.properties.attachmentId.type, 'string')
  assert.match(renderToolsSdk([{ name: definition.name, parameters: definition.parameters, output: definition.output.schema }]), /attachmentId: string/)
  assert.deepEqual(await readFile(join(directory, 'image.png')), png)
  assert.equal(requests.length, 2)
  assert.deepEqual(requests[0].body, { query: 'diagram', urls: ['https://example.org/page'], verify_images: true, refresh: false, max_images: 3 })
  assert.ok(requests.every(req => req.authorization === 'Bearer test-secret'))
  const text = result.content[0].text
  assert.ok(text.includes(`\n\n${result.value.images[0].markdown}\n\nImage source:`), 'the example must separate the image and its source into Markdown paragraphs')
  assert.match((await ctx.systemPrompt.assemble()).sections.find(section => section.name === 'tool:citeweave_search').text, /blank line before and after/)
  assert.match(text, /!\[A \\\[diagram\\\]\]\(/)
  assert.match(text, /citeweave%20test%20/)
  assert.match(text, /https:\/\/example.org\/%E7%8B%AE%E5%AD%90\?q=1&lang=en&name=a%20b/)
  assert.match(text, /https:\/\/example.org\/missing: fetch failed/)
  assert.match(text, /expected a CiteWeave \/cache\/ image URL/)
  assert.ok(!text.includes('test-secret'))
  assert.equal((await call({ query: 'empty' })).value.images.length, 0)
  assert.equal((await call({ query: ' ' })).isError, true)
  assert.equal((await call({ query: 'test', urls: ['file:///etc/passwd'] })).isError, true)
  assert.equal((await call({ query: 'test', urls: [] })).isError, true)
  const malformed = await call({ query: 'malformed' })
  assert.equal(malformed.isError, true)
  assert.match(malformed.content[0].text, /Invalid CiteWeave evidence response/)
  const imageDenied = await call({ query: 'denied-image' })
  assert.equal(imageDenied.isError, false)
  assert.equal(imageDenied.value.images.length, 0)
  assert.match(imageDenied.value.retrieval_errors.join('; '), /Image i1:.*HTTP 401.*check accessToken/)

  const controller = new AbortController()
  const pending = call({ query: 'slow' }, controller.signal)
  await started
  controller.abort()
  const aborted = await pending
  assert.equal(aborted.isError, true)
  assert.match(aborted.content[0].text, /abort/i)

  await fiber.dispose()
  assert.equal(ctx.tools.get('citeweave_search'), undefined)
  assert.ok(!(await ctx.systemPrompt.assemble()).sections.some(section => section.name === 'tool:citeweave_search'))
  await ctx.plugin(plugin, { endpoint, accessToken: 'incorrect' }).await()
  const denied = await call({ query: 'test' })
  assert.equal(denied.isError, true)
  assert.match(denied.content[0].text, /HTTP 401.*check accessToken/)
})
