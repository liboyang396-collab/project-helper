export type Project = {
  id: number
  repo_url: string
  repo_name: string
  status: string
  branch: string
  commit_sha: string
  report_markdown: string
  summary: Record<string, unknown>
  error_message: string
  created_at: string
  updated_at: string
}

export type AnalyzeResponse = {
  project: Project
  cached: boolean
  events_url: string
}

export type ProgressEvent = {
  id: number
  stage: string
  message: string
  progress: number
  created_at: string
}

const jsonHeaders = { 'Content-Type': 'application/json' }

export async function listProjects(): Promise<Project[]> {
  const res = await fetch('/api/projects')
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getProject(id: number): Promise<Project> {
  const res = await fetch(`/api/projects/${id}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function analyzeProject(repoUrl: string, force = false): Promise<AnalyzeResponse> {
  const res = await fetch('/api/projects/analyze', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ repo_url: repoUrl, force })
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function streamChat(
  projectId: number,
  question: string,
  onEvent: (event: string, data: Record<string, unknown>) => void
) {
  const res = await fetch(`/api/projects/${projectId}/chat/stream`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ question })
  })
  if (!res.ok || !res.body) throw new Error(await res.text())

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const lines = frame.split('\n')
      const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() ?? 'message'
      const dataLine = lines.find((line) => line.startsWith('data:'))?.slice(5).trim()
      if (!dataLine) continue
      onEvent(event, JSON.parse(dataLine))
    }
  }
}
