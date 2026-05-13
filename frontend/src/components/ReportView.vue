<script setup lang="ts">
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import { computed } from 'vue'
import { FileText } from 'lucide-vue-next'

const props = defineProps<{
  markdown: string
  status: string
}>()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  highlight(code: string, lang: string) {
    const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
    return `<pre class="hljs"><code>${hljs.highlight(code, { language }).value}</code></pre>`
  }
})

const html = computed(() => (props.markdown ? md.render(props.markdown) : ''))
</script>

<template>
  <section class="report-surface">
    <div class="section-header">
      <div>
        <p class="eyebrow">Analysis Report</p>
        <h2>源码学习报告</h2>
      </div>
      <div class="status-pill" :data-status="status">
        <FileText :size="16" />
        <span>{{ status }}</span>
      </div>
    </div>

    <article v-if="markdown" class="markdown-body" v-html="html" />
    <div v-else class="empty-state">
      <FileText :size="42" />
      <h3>等待一份可读的源码地图</h3>
      <p>输入 GitHub 仓库地址后，这里会显示项目概述、目录结构、核心模块、数据流和阅读路线。</p>
    </div>
  </section>
</template>
