import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const root = new URL('..', import.meta.url).pathname
const catalogs = ['en', 'zh'].map((locale) => ({
  locale,
  path: join(root, 'src', 'i18n', 'locales', locale, 'messages.po'),
}))

let failed = false

for (const catalog of catalogs) {
  const text = readFileSync(catalog.path, 'utf8')
  const active = [...text.matchAll(/^msgid\s+"(.*)"$/gm)]
    .map((match) => match[1])
    .filter((id) => id !== '')
  const obsolete = [...text.matchAll(/^#~ msgid\s+"(.*)"$/gm)]
    .map((match) => match[1])
    .filter((id) => id !== '')

  if (active.length === 0) {
    console.error(`${catalog.locale}: no active Lingui messages in ${catalog.path}`)
    failed = true
  }
  if (obsolete.length > active.length) {
    console.error(
      `${catalog.locale}: obsolete Lingui messages (${obsolete.length}) exceed active messages (${active.length}); ` +
        'do not rely on #~ entries surviving lingui extract --clean',
    )
    failed = true
  }
}

if (failed) process.exit(1)
