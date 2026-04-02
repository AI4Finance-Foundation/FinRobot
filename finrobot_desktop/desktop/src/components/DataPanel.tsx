import { ReactNode } from 'react'

interface DataPanelProps {
  title?: string
  children: ReactNode
}

export default function DataPanel({ title, children }: DataPanelProps) {
  return (
    <div className="space-y-4">
      {title && (
        <h3 className="text-lg font-semibold text-gray-200">{title}</h3>
      )}
      {children}
    </div>
  )
}

interface DataCardProps {
  title: string
  children: ReactNode
}

export function DataCard({ title, children }: DataCardProps) {
  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h4 className="text-sm font-medium text-gray-400 mb-2">{title}</h4>
      {children}
    </div>
  )
}
