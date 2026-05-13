import '@testing-library/jest-dom'

// jsdom does not implement ResizeObserver — polyfill for component tests that
// use cmdk (which internally uses @radix-ui/react-dialog → ResizeObserver).
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

// jsdom does not implement scrollIntoView — cmdk uses it for keyboard nav.
if (typeof Element.prototype.scrollIntoView === 'undefined') {
  Element.prototype.scrollIntoView = function () {}
}

// Suppress Radix Dialog accessibility warnings in test output (we add aria-label
// via Command.Dialog's label prop; the VisuallyHidden title warning is cosmetic).
const originalConsoleError = console.error
console.error = (...args: unknown[]) => {
  const msg = typeof args[0] === 'string' ? args[0] : ''
  if (
    msg.includes('DialogTitle') ||
    msg.includes('DialogContent') ||
    msg.includes('aria-describedby')
  ) {
    return
  }
  originalConsoleError(...args)
}
