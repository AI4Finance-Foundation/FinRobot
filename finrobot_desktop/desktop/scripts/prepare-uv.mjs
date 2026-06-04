/**
 * Copies the local `uv` binary into build/uv-sidecar/ for electron-builder
 * to bundle as an extraResource.
 *
 * Usage: node scripts/prepare-uv.mjs
 */
import { execSync } from 'child_process'
import { copyFileSync, mkdirSync, chmodSync } from 'fs'
import { join } from 'path'

const outDir = join(import.meta.dirname, '..', 'build', 'uv-sidecar')
mkdirSync(outDir, { recursive: true })

// Find uv binary path
const uvPath = execSync('which uv', { encoding: 'utf-8' }).trim()
if (!uvPath) {
  console.error('Error: uv not found. Install it: https://docs.astral.sh/uv/')
  process.exit(1)
}

const isWin = process.platform === 'win32'
const dest = join(outDir, isWin ? 'uv.exe' : 'uv')

copyFileSync(uvPath, dest)
chmodSync(dest, 0o755)

console.log(`Copied uv: ${uvPath} -> ${dest}`)
