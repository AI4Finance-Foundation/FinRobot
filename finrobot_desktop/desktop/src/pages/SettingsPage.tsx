import SettingsView from '../views/SettingsView'

// SettingsView owns the whole settings surface (header, section nav, content +
// the appearance/language section). This page is just the route wrapper.
export function SettingsPage() {
  return <SettingsView />
}
