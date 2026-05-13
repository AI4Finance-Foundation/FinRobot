import { useState, useCallback, useRef, useEffect } from 'react'
import { BASE_URL } from '../api/client'

export interface RunStep {
  name: string
  status: 'pending' | 'running' | 'completed' | 'retrying'
  duration_s?: number
}

type StreamStatus = 'idle' | 'running' | 'completed' | 'failed'

export interface UseRunStreamReturn {
  steps: RunStep[]
  status: StreamStatus
  error: string | null
  progress: number // 0-1
  startRun: (pipelineType: string, ticker: string) => Promise<string>
}

export function useRunStream(): UseRunStreamReturn {
  const [steps, setSteps] = useState<RunStep[]>([])
  const [status, setStatus] = useState<StreamStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const esRef = useRef<EventSource | null>(null)
  // F3 fix: keep latest status in a ref so onerror closure reads current value
  const statusRef = useRef<StreamStatus>('idle')
  statusRef.current = status

  // F1 fix: close EventSource on unmount
  useEffect(() => {
    return () => {
      esRef.current?.close()
      esRef.current = null
    }
  }, [])

  const startRun = useCallback(async (pipelineType: string, ticker: string): Promise<string> => {
    // Close any previous connection
    esRef.current?.close()
    esRef.current = null

    // Reset state
    setSteps([])
    setStatus('running')
    setError(null)
    setProgress(0)

    // POST to create run
    const resp = await fetch(`${BASE_URL}/api/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pipeline_type: pipelineType, ticker }),
    })
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}))
      const msg = body.detail || `Run creation failed (${resp.status})`
      setError(msg)
      setStatus('failed')
      throw new Error(msg)
    }
    const { run_id } = await resp.json()

    // Connect SSE
    const es = new EventSource(`${BASE_URL}/api/runs/${run_id}/events`)
    esRef.current = es

    es.addEventListener('run.started', (e) => {
      const data = JSON.parse(e.data)
      const totalSteps = data.total_steps || 4
      setSteps(
        Array.from({ length: totalSteps }, (_, i) => ({
          name: `Step ${i + 1}`,
          status: 'pending' as const,
        }))
      )
    })

    es.addEventListener('step.started', (e) => {
      const data = JSON.parse(e.data)
      setSteps((prev) =>
        prev.map((s, i) =>
          i === data.step - 1 ? { ...s, name: data.name, status: 'running' } : s
        )
      )
      setProgress(Math.max(0, (data.step - 1) / data.total))
    })

    es.addEventListener('step.completed', (e) => {
      const data = JSON.parse(e.data)
      setSteps((prev) =>
        prev.map((s, i) =>
          i === data.step - 1
            ? { ...s, name: data.name, status: 'completed', duration_s: data.duration_s }
            : s
        )
      )
      setProgress(data.step / data.total)
    })

    es.addEventListener('step.retry', (e) => {
      const data = JSON.parse(e.data)
      setSteps((prev) =>
        prev.map((s, i) =>
          i === data.step - 1 ? { ...s, name: data.name, status: 'retrying' } : s
        )
      )
    })

    es.addEventListener('run.completed', () => {
      setStatus('completed')
      setProgress(1)
      es.close()
      esRef.current = null
    })

    es.addEventListener('run.failed', (e) => {
      const data = JSON.parse(e.data)
      setError(data.error || 'Pipeline failed')
      setStatus('failed')
      es.close()
      esRef.current = null
    })

    // F3 fix: read from statusRef (current value) instead of stale closure
    es.onerror = () => {
      if (statusRef.current === 'completed' || statusRef.current === 'failed') {
        es.close()
        esRef.current = null
      }
    }

    return run_id
  }, [])

  return { steps, status, error, progress, startRun }
}
