// Flags active Lingui msgids that no source file references — the gap
// check-lingui-catalogs.mjs (en/zh parity only) can't see, which let the dead
// `report.rightRail.timeline` key linger after its component was deleted.
//
// A key counts as USED when its literal string appears anywhere in src/ OR it falls
// under a dynamic key prefix. Dynamic prefixes come from the static head of ANY
// template literal that interpolates (`chapter.ownership.degraded.${section}.x` →
// "chapter.ownership.degraded.") — NOT only t(`…`) calls, since keys are frequently
// assembled in helper maps / objects and only later passed to t(). A prefix is kept
// only when it actually prefixes a real key, so non-i18n templates (`${BASE}/api`,
// `${wacc}_${tg}`) mask nothing. The check would rather miss a buried orphan than
// flag a legitimately-used key — a false positive would block a clean commit.
//
// Exits 1 (with the orphan list) when any active key is unreferenced.

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = new URL('..', import.meta.url).pathname
const SRC = join(ROOT, 'src')
const PO = join(SRC, 'i18n', 'locales', 'en', 'messages.po')

// Exclude the generated catalogs (the .po/.mjs ARE the key definitions) and the
// compiled export bundle (a minified copy of the whole catalog).
const EXCLUDE = ['i18n/locales', 'export/generated']

function collectSource(dir, acc) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    const rel = full.slice(SRC.length + 1).replace(/\\/g, '/')
    if (EXCLUDE.some((e) => rel.startsWith(e))) continue
    if (statSync(full).isDirectory()) collectSource(full, acc)
    else if (/\.(ts|tsx|js|mjs)$/.test(name) && !name.endsWith('.d.ts')) {
      acc.push(readFileSync(full, 'utf8'))
    }
  }
  return acc
}

/** Pure core (exported for unit tests): active msgids + a concatenated source blob
 * → the unreferenced keys. A key is referenced if its literal appears in source, or
 * it starts with a dynamic prefix that itself prefixes some real key. */
export function findOrphans(active, src) {
  const dynamicPrefixes = [...src.matchAll(/`([^`$]*)\$\{/g)]
    .map((m) => m[1])
    .filter((p) => p.includes('.') && active.some((k) => k.startsWith(p)))
  return active
    .filter((k) => !src.includes(k) && !dynamicPrefixes.some((p) => k.startsWith(p)))
    .sort()
}

function main() {
  const src = collectSource(SRC, []).join('\n')
  const po = readFileSync(PO, 'utf8')
  const active = [...po.matchAll(/^msgid\s+"(.*)"$/gm)].map((m) => m[1]).filter(Boolean)
  const orphans = findOrphans(active, src)

  if (orphans.length > 0) {
    console.error(
      `i18n orphans: ${orphans.length} active key(s) in en/messages.po are referenced ` +
        `nowhere in src/ (neither as a literal nor under a dynamic t(\`prefix.\${…}\`)):`,
    )
    for (const k of orphans) console.error(`  ${k}`)
    console.error(
      '\nFix: remove each from src/i18n/locales/{en,zh}/messages.po and recompile ' +
        '(npx lingui compile), or add the missing reference. If a key is built ' +
        'dynamically, expose its prefix via a `prefix.${…}` template the check can see.',
    )
    process.exit(1)
  }

  console.log(`i18n orphans: none — all ${active.length} active keys are referenced.`)
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main()
