// Shared artifact type → display label. Its own module so both AIZone (toasts,
// OtherArtifacts rows) and ValuationInstruments can name an artifact type
// identically without a circular import. Mirror of CompactArtifactViewer's
// TYPE_LABEL so the workspace and the detail page name the same artifact the
// same way. Inline literals per the VersionDiffBanner precedent (short, stable
// model names — not .po catalogue strings).
import type { Locale } from '../../i18n'

export const ARTIFACT_TYPE_LABEL: Record<string, { zh: string; en: string }> = {
  dcf: { zh: 'DCF 估值', en: 'DCF Valuation' },
  lbo: { zh: 'LBO 模型', en: 'LBO Model' },
  ddm: { zh: 'DDM 股利贴现', en: 'DDM Valuation' },
  comps: { zh: '可比公司', en: 'Comparable Companies' },
  earnings: { zh: '财报质量', en: 'Earnings Quality' },
  ic_memo: { zh: '投委会备忘录', en: 'IC Memo' },
  peer_research: { zh: '同业研究', en: 'Peer Research' },
  ad_hoc: { zh: '即席分析', en: 'Ad-hoc Analysis' },
}

export function artifactTypeLabel(type: string, locale: Locale): string {
  const m = ARTIFACT_TYPE_LABEL[type]
  if (m) return locale === 'zh' ? m.zh : m.en
  return type
}
