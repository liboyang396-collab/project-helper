<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import { Bot, Send, TerminalSquare } from 'lucide-vue-next'
import { streamChat, type Project } from '../services/api'

const props = defineProps<{
  project: Project | null
}>()

type ChatMessage = {
  role: 'user' | 'assistant' | 'system'
  content: string
}

const messages = ref<ChatMessage[]>([])
const question = ref('')
const streaming = ref(false)
const error = ref('')
const feedRef = ref<HTMLElement | null>(null)

const md = new MarkdownIt({
  html: false,
  linkify: true,
  highlight(code: string, lang: string) {
    const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
    return `<pre class="hljs"><code>${hljs.highlight(code, { language }).value}</code></pre>`
  }
})

const canAsk = computed(() => props.project?.status === 'completed' && !streaming.value)

function scrollToLatest() {
  nextTick(() => {
    if (!feedRef.value) return
    feedRef.value.scrollTop = feedRef.value.scrollHeight
  })
}

async function ask() {
  const text = question.value.trim()
  if (!text || !props.project || !canAsk.value) return
  error.value = ''
  messages.value.push({ role: 'user', content: text })
  const answer: ChatMessage = { role: 'assistant', content: '' }
  messages.value.push(answer)
  question.value = ''
  streaming.value = true
  scrollToLatest()

  try {
    await streamChat(props.project.id, text, (event, data) => {
      if (event === 'delta') {
        answer.content += String(data.content ?? '')
        scrollToLatest()
      }
      if (event === 'agent') {
        const payload = String(data.payload ?? '').trim()
        if (payload) answer.content += `${answer.content ? '\n\n' : ''}${payload}`
        scrollToLatest()
      }
      if (event === 'error') {
        error.value = String(data.message ?? 'Agent 调用失败')
      }
    })
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc)
  } finally {
    streaming.value = false
  }
}
</script>

<template>
  <aside class="chat-panel">
    <div class="section-header compact">
      <div>
        <p class="eyebrow">Code Agent</p>
        <h2>源码问答</h2>
      </div>
      <Bot :size="20" />
    </div>

    <div ref="feedRef" class="chat-feed">
      <div v-if="!messages.length" class="agent-hint">
        <TerminalSquare :size="30" />
        <p>分析完成后，可以问“登录流程怎么走？”、“这个函数被谁调用？”、“我应该先读哪些文件？”。</p>
      </div>

      <div v-for="(message, index) in messages" :key="index" class="chat-message" :data-role="message.role">
        <span>{{ message.role === 'user' ? 'You' : 'Agent' }}</span>
        <div v-html="md.render(message.content || (streaming ? '正在查代码...' : ''))" />
      </div>
    </div>

    <p v-if="error" class="inline-error">{{ error }}</p>

    <form class="chat-form" @submit.prevent="ask">
      <textarea
        v-model="question"
        rows="3"
        :disabled="!project || project.status !== 'completed'"
        placeholder="针对源码提问，让 Agent 自己找文件回答"
      />
      <button type="submit" :disabled="!canAsk || !question.trim()" aria-label="发送问题">
        <Send :size="18" />
      </button>
    </form>
  </aside>
</template>
