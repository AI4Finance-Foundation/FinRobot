import { useState, useCallback, useRef } from 'react'

export interface PipelineEvent {
  step: string
  status: 'running' | 'completed' | 'failed'
  text: string
  structured: Record<string, unknown> | null
  progress: number
}

export type StreamStatus = 'idle' | 'running' | 'completed' | 'failed'

export interface UsePipelineStreamReturn {
  events: PipelineEvent[]
  status: StreamStatus
  progress: number
  error: string | null
  start: () => void
}

const SERVER_URL = 'http://127.0.0.1:8000'

export function usePipelineStream(
  endpoint: string,
  params: Record<string, string>,
): UsePipelineStreamReturn {
  const [events, setEvents] = useState<PipelineEvent[]>([])
  const [status, setStatus] = useState<StreamStatus>('idle')
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)

  // Track whether the connection is intentionally active to avoid stale-closure
  // issues in the onerror callback (which captures status from an older render).
  const activeRef = useRef(false)

  const start = useCallback(() => {
    setEvents([])
    setStatus('running')
    setProgress(0)
    setError(null)
    activeRef.current = true

    const url = new URL(`${SERVER_URL}${endpoint}`)
    Object.entries(params).forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v)
    })

    const es = new EventSource(url.toString())

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as PipelineEvent
        setEvents((prev) => [...prev, event])
        setProgress(event.progress)

        if (event.status === 'failed') {
          activeRef.current = false
          setStatus('failed')
          setError(event.text)
          es.close()
        } else if (event.status === 'completed' && event.progress >= 1.0) {
          activeRef.current = false
          setStatus('completed')
          es.close()
        }
      } catch {
        console.error('Failed to parse SSE event:', e.data)
      }
    }

    es.onerror = () => {
      // EventSource fires error on normal connection close.
      // Only treat as error if we haven't already completed/failed via onmessage.
      if (activeRef.current) {
        activeRef.current = false
        setStatus('failed')
        setError('Connection to server lost')
      }
      es.close()
    }
  }, [endpoint, params])

  return { events, status, progress, error, start }
}
