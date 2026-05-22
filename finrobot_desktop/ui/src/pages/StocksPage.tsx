// StocksPage — /stocks landing route.
//
// Cosmic Stage A rewrite: thin shell that hosts the new
// pages/landing/StocksLandingHero composition (search + hit-rate banner +
// recent research strip + hot ticker chips). Spec §2.2.

import { StocksLandingHero } from './landing/StocksLandingHero'

export function StocksPage(): React.ReactElement {
  return <StocksLandingHero />
}
