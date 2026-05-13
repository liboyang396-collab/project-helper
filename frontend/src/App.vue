<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  AlertCircle,
  CheckCircle2,
  Github,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Server
} from 'lucide-vue-next'
import ChatPanel from './components/ChatPanel.vue'
import ReportView from './components/ReportView.vue'
import StatusTimeline from './components/StatusTimeline.vue'
import {
  analyzeProject,
  getProject,
  listProjects,
  type ProgressEvent,
  type Project
} from './services/api'

const repoUrl = ref('https://github.com/tiangolo/fastapi')
const projects = ref<Project[]>([])
const selected = ref<Project | null>(null)
const events = ref<ProgressEvent[]>([])
const loading = ref(false)
const force = ref(false)
const error = ref('')
let eventSource: EventSource | null = null

const progress = computed(() => events.value.at(-1)?.progress ?? (selected.value?.status === 'completed' ? 100 : 0))

async function refreshProjects() {
  projects.value = await listProjects()
  if (!selected.value && projects.value.length) {
    selected.value = projects.value[0]
  }
}

function closeEvents() {
  eventSource?.close()
  eventSource = null
}

function watchProgress(projectId: number) {
  closeEvents()
  eventSource = new EventSource(`/api/projects/${projectId}/events`)
  eventSource.addEventListener('progress', (raw) => {
    const data = JSON.parse((raw as MessageEvent).data) as ProgressEvent
    events.value.push(data)
  })
  for (const name of ['completed', 'failed']) {
    eventSource.addEventListener(name, async () => {
      closeEvents()
      selected.value = await getProject(projectId)
      await refreshProjects()
      loading.value = false
    })
  }
  eventSource.onerror = () => {
    closeEvents()
    loading.value = false
  }
}

async function startAnalysis() {
  error.value = ''
  loading.value = true
  events.value = []
  try {
    const response = await analyzeProject(repoUrl.value, force.value)
    selected.value = response.project
    if (response.cached) {
      events.value = [{ id: 0, stage: 'cache', message: '命中缓存，直接读取已有报告', progress: 100, created_at: new Date().toISOString() }]
      loading.value = false
    } else {
      watchProgress(response.project.id)
    }
    await refreshProjects()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc)
    loading.value = false
  }
}

async function selectProject(project: Project) {
  selected.value = await getProject(project.id)
  events.value = []
  if (!['completed', 'failed'].includes(selected.value.status)) {
    loading.value = true
    watchProgress(project.id)
  }
}

onMounted(async () => {
  try {
    await refreshProjects()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc)
  }
})
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark"><Server :size="22" /></div>
        <div>
          <strong>Project Helper</strong>
          <span>项目学习助手</span>
        </div>
      </div>
      <div class="topbar-status">
        <CheckCircle2 v-if="selected?.status === 'completed'" :size="17" />
        <AlertCircle v-else-if="selected?.status === 'failed'" :size="17" />
        <Loader2 v-else-if="loading" class="spin" :size="17" />
        <span>{{ selected?.repo_name ?? '等待仓库' }}</span>
      </div>
    </header>

    <section class="command-band">
      <div class="command-copy">
        <p class="eyebrow">Repository Intake</p>
        <h1>把 GitHub 仓库变成能读懂的源码地图</h1>
      </div>
      <form class="repo-form" @submit.prevent="startAnalysis">
        <label for="repo-url">GitHub 仓库地址</label>
        <div class="input-row">
          <Github :size="20" />
          <input id="repo-url" v-model="repoUrl" type="url" placeholder="https://github.com/owner/repo" required />
          <button type="submit" :disabled="loading" aria-label="开始分析">
            <Loader2 v-if="loading" class="spin" :size="18" />
            <Play v-else :size="18" />
            <span>{{ loading ? '分析中' : '开始分析' }}</span>
          </button>
        </div>
        <label class="force-toggle">
          <input v-model="force" type="checkbox" />
          <span>重新分析并刷新缓存</span>
        </label>
        <p v-if="error" class="inline-error">{{ error }}</p>
      </form>
    </section>

    <div class="workspace-grid">
      <aside class="sidebar">
        <div class="section-header compact">
          <div>
            <p class="eyebrow">Cache</p>
            <h2>历史项目</h2>
          </div>
          <button class="icon-button" type="button" aria-label="刷新历史项目" @click="refreshProjects">
            <RefreshCw :size="17" />
          </button>
        </div>

        <div class="project-list">
          <button
            v-for="project in projects"
            :key="project.id"
            class="project-item"
            :class="{ active: selected?.id === project.id }"
            type="button"
            @click="selectProject(project)"
          >
            <Search :size="16" />
            <span>{{ project.repo_name }}</span>
            <small>{{ project.status }}</small>
          </button>
        </div>

        <StatusTimeline :events="events" :status="selected?.status ?? 'idle'" :progress="progress" />
      </aside>

      <ReportView :markdown="selected?.report_markdown ?? ''" :status="selected?.status ?? 'idle'" />
      <ChatPanel :project="selected" />
    </div>
  </main>
</template>
