// Locks the orphan detector's reference logic — especially that keys assembled in a
// helper map (not directly inside t()) are NOT mis-flagged. That exact gap once
// deleted the live `chapter.ownership.degraded.insiders.*` keys before the full test
// suite caught it; this keeps the dynamic-prefix handling from regressing either way.

import { describe, it, expect } from 'vitest'

import { findOrphans } from './check-i18n-orphans.mjs'

describe('findOrphans', () => {
  it('keeps statically-referenced keys, flags the rest', () => {
    expect(findOrphans(['a.used', 'a.dead'], `t('a.used')`)).toEqual(['a.dead'])
  })

  it('keeps keys under a dynamic t(`prefix.${x}`) template', () => {
    const src = 't(`chart.footballField.history.${clsKey}`)'
    expect(
      findOrphans(
        ['chart.footballField.history.cheap', 'chart.footballField.history.rich', 'x.dead'],
        src,
      ),
    ).toEqual(['x.dead'])
  })

  it('keeps keys assembled in a helper map template, not just inside t() (ownership regression)', () => {
    // The exact shape that broke once: the key is built in an object value and only
    // later passed to t(). The prefix before `${section}` must still cover it.
    const src = 'const m = { no_recent_filings: `chapter.ownership.degraded.${section}.no_recent_filings` }'
    expect(
      findOrphans(
        [
          'chapter.ownership.degraded.insiders.no_recent_filings',
          'chapter.ownership.degraded.compensation.no_recent_filings',
        ],
        src,
      ),
    ).toEqual([])
  })

  it('flags genuinely-unreferenced keys', () => {
    expect(findOrphans(['x.dead', 'y.dead'], 'const a = 1')).toEqual(['x.dead', 'y.dead'])
  })

  it('does not let non-i18n templates mask real keys', () => {
    // `${BASE}/api` → empty prefix (no dot, dropped); `${wacc}_${tg}` → empty prefix;
    // `foo.bar.${x}` → prefix "foo.bar." but no active key starts with it → no mask.
    const src = 'fetch(`${BASE}/api/${id}`); k(`${wacc}_${tg}`); css(`foo.bar.${x}`)'
    expect(findOrphans(['real.dead'], src)).toEqual(['real.dead'])
  })
})
