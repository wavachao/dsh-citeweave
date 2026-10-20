import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync } from 'node:fs'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { ...options, stdio: ['ignore', 'pipe', 'pipe'] })
    let stdout = '', stderr = ''
    child.stdout.on('data', chunk => { stdout += chunk })
    child.stderr.on('data', chunk => { stderr += chunk })
    child.on('error', reject)
    child.on('close', code => code === 0 ? resolve(stdout) : reject(new Error(`${command} exited ${code}\n${stdout}\n${stderr}`)))
  })
}

export function npm(args, options = {}) {
  const candidates = [process.env.npm_execpath,
    join(dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js'),
    resolve(dirname(process.execPath), '../lib/node_modules/npm/bin/npm-cli.js')]
  const cli = candidates.find(path => path && existsSync(path))
  if (!cli) throw new Error('Run this command through npm to locate its CLI.')
  return run(process.execPath, [cli, ...args], options)
}

export async function pack(destination) {
  await mkdir(destination, { recursive: true })
  const [archive] = JSON.parse(await npm(['pack', '--json', '--pack-destination', destination]))
  return { ...archive, path: join(destination, archive.filename) }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const manifest = JSON.parse(await readFile('package.json', 'utf8'))
  if (process.env.GITHUB_REF_TYPE === 'tag' && process.env.GITHUB_REF_NAME !== `v${manifest.version}`) {
    throw new Error('Release tag must match package.json version.')
  }
  const archive = await pack(resolve('dist'))
  const digest = createHash('sha256').update(await readFile(archive.path)).digest('hex')
  await writeFile(resolve('dist/SHA256SUMS'), `${digest}  ${archive.filename}\n`)
  const changelog = await readFile('CHANGELOG.md', 'utf8')
  const section = changelog.split(/^## /m).find(section => section.startsWith(`[${manifest.version}]`))
  if (!section) throw new Error(`CHANGELOG.md has no entry for ${manifest.version}.`)
  await writeFile(resolve('dist/RELEASE_NOTES.md'), section.slice(section.indexOf('\n') + 1).trim() + '\n')
  console.log(`${archive.filename}\nSHA256 ${digest}`)
}
