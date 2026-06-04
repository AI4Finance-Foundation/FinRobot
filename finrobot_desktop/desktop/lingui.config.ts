import type { LinguiConfig } from "@lingui/conf"
import { formatter } from "@lingui/format-po"

const config: LinguiConfig = {
  sourceLocale: "zh",
  locales: ["zh", "en"],
  catalogs: [
    {
      path: "<rootDir>/src/i18n/locales/{locale}/messages",
      include: ["src"],
    },
  ],
  format: formatter({ lineNumbers: false }),
  compileNamespace: "es",
}

export default config
