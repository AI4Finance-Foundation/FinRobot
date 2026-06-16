// Canonical AI4Finance Foundation / FinRobot external links + brand strings.
// Single source so the global footer (AppFooter) and the brand About popover
// (BrandAbout) can never drift apart.

/** Legal name of the owning organization (a registered 501(c)(3) public
 *  charity — IRS Pub 78 / GuideStar EIN 99-1488572). Proper noun: never
 *  translated. */
export const FOUNDATION_NAME = 'AI4Finance Foundation'

export const EXTERNAL_LINKS = {
  /** Foundation homepage. */
  site: 'https://ai4finance.org',
  /** Public FinRobot repository — the "Star on GitHub" target. Points at the
   *  foundation's flagship open-source repo to drive its star count; repoint
   *  here if the rewrite ships its own public repository. */
  github: 'https://github.com/AI4Finance-Foundation/FinRobot',
} as const

/** Display label for the site link (the URL without its scheme). */
export const SITE_LABEL = 'ai4finance.org'
