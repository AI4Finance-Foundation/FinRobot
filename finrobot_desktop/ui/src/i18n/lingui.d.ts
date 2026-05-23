// Type declarations for compiled Lingui catalogs.
//
// `npx lingui compile` regenerates these .mjs files from the .po sources.
// The compiled module exports a single `messages` constant — a Lingui internal
// JSON-encoded map { id: [segments | placeholder-arrays] }.

declare module '*/locales/zh/messages.mjs' {
  export const messages: Record<string, unknown>
}

declare module '*/locales/en/messages.mjs' {
  export const messages: Record<string, unknown>
}
