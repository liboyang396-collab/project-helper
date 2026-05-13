<script setup lang="ts">
import { AlertCircle, CheckCircle2, Clock3, Loader2 } from 'lucide-vue-next'
import type { ProgressEvent } from '../services/api'

defineProps<{
  events: ProgressEvent[]
  status: string
  progress: number
}>()
</script>

<template>
  <section class="progress-panel">
    <div class="section-header compact">
      <div>
        <p class="eyebrow">Live Progress</p>
        <h2>分析进度</h2>
      </div>
      <CheckCircle2 v-if="status === 'completed'" class="ok" :size="20" />
      <AlertCircle v-else-if="status === 'failed'" class="danger" :size="20" />
      <Loader2 v-else class="spin" :size="20" />
    </div>

    <div class="progress-track" aria-label="analysis progress">
      <span :style="{ width: `${progress}%` }" />
    </div>

    <ol class="timeline">
      <li v-for="event in events" :key="event.id">
        <Clock3 :size="14" />
        <div>
          <strong>{{ event.stage }}</strong>
          <p>{{ event.message }}</p>
        </div>
        <span>{{ event.progress }}%</span>
      </li>
    </ol>
  </section>
</template>
