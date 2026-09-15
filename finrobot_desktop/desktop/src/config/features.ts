const ENABLED_VALUES = new Set(['1', 'true', 'yes', 'on'])

function envFlag(value: string | undefined): boolean {
  return value === undefined ? false : ENABLED_VALUES.has(value.toLowerCase())
}

export const AI_CHAT_ENABLED = envFlag(import.meta.env.VITE_ENABLE_AI_CHAT)
