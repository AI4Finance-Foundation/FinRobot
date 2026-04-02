import { ReactNode } from 'react'

interface LayoutProps {
  leftPanel: ReactNode
  rightPanel: ReactNode | null
  progress?: number
  progressLabel?: string
}

export default function Layout({ leftPanel, rightPanel, progress, progressLabel }: LayoutProps) {
  return (
    <div className="flex flex-col h-full">
      <div className="flex flex-1 min-h-0">
        {/* Left panel — analysis text/results */}
        <div className="flex-1 overflow-y-auto p-4">
          {leftPanel}
        </div>

        {/* Right panel — charts/data (only shown when content exists) */}
        {rightPanel && (
          <div className="w-[45%] border-l border-gray-700 overflow-y-auto p-4">
            {rightPanel}
          </div>
        )}
      </div>

      {/* Bottom progress bar */}
      {progress != null && progress > 0 && (
        <div className="border-t border-gray-700 px-4 py-2 flex items-center gap-3">
          <div className="flex-1 bg-gray-800 rounded-full h-2">
            <div
              className="bg-[#d4a843] h-2 rounded-full transition-all duration-300"
              style={{ width: `${Math.min(progress * 100, 100)}%` }}
            />
          </div>
          {progressLabel && (
            <span className="text-sm text-gray-400 whitespace-nowrap">{progressLabel}</span>
          )}
        </div>
      )}
    </div>
  )
}
