<script setup>
// The accepted queue for the selected run (PRD 8.5, M7-T3): one card per role,
// with the three things you do to it - open it, mark it applied, or dismiss it.
// Status is written to the server; Dismiss is local to this session (Q2).
import { computed, ref } from 'vue'
import { setApplicationStatus } from '../api.js'
import { dismiss, isDismissed, restoreAll } from '../dismissed.js'

const props = defineProps({
  run: { type: [Number, String], default: null },
  jobs: { type: Array, required: true },
})
const emit = defineEmits(['changed'])

const busy = ref(new Set())
const error = ref('')

const visible = computed(() => props.jobs.filter(j => !isDismissed(j.id)))
const hidden = computed(() => props.jobs.filter(j => isDismissed(j.id)))

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function shortDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '')
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}` : ''
}

// Posting URLs are scraped from third-party boards. Only http(s) becomes a
// link, so a `javascript:` URL in a feed can never run in this page.
function safeUrl(url) {
  return /^https?:\/\//i.test(url || '') ? url : null
}

function years(job) {
  if (job.yoe_min === null || job.yoe_min === undefined) return null
  return `${job.yoe_min} yr${job.yoe_min === 1 ? '' : 's'}`
}

function meta(job) {
  const seen = shortDate(job.decided_at)
  return [job.location, years(job), seen && `seen ${seen}`].filter(Boolean).join(' · ')
}

// Any status other than to_apply means the application has been made.
function alreadyApplied(job) {
  return Boolean(job.status) && job.status !== 'to_apply'
}

async function markApplied(job) {
  error.value = ''
  busy.value = new Set(busy.value).add(job.id)
  try {
    await setApplicationStatus(job.id, 'applied', {
      company: job.company, role: job.title, url: job.url,
    })
    emit('changed')
  } catch (e) {
    error.value = `Could not mark ${job.company} · ${job.title} applied: ${e.message || e}`
  } finally {
    const next = new Set(busy.value)
    next.delete(job.id)
    busy.value = next
  }
}
</script>

<template>
  <section class="inbox">
    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <p class="count">
      {{ visible.length }} role{{ visible.length === 1 ? '' : 's' }}
      <template v-if="hidden.length">
        · {{ hidden.length }} dismissed this session
        <button type="button" class="link" @click="restoreAll(hidden.map(j => j.id))">show</button>
      </template>
    </p>

    <p v-if="!jobs.length" class="empty">No roles in this run.</p>

    <ul class="cards">
      <li v-for="job in visible" :key="job.id" class="card" :class="{ closed: job.closed }">
        <div class="head">
          <span class="company">{{ job.company }}</span>
          <span class="sep">·</span>
          <span class="title">{{ job.title }}</span>
          <span v-if="job.status" class="status" :data-status="job.status">{{ job.status }}</span>
          <span v-if="job.closed" class="stale" title="The posting has been taken down">closed</span>
        </div>
        <div class="meta">{{ meta(job) }}</div>
        <p v-if="job.reason" class="reason">“{{ job.reason }}”</p>
        <ul v-if="job.matched_skills && job.matched_skills.length" class="skills">
          <li v-for="skill in job.matched_skills" :key="skill">{{ skill }}</li>
        </ul>
        <div class="actions">
          <a
            v-if="safeUrl(job.url)"
            class="open"
            :href="safeUrl(job.url)"
            target="_blank"
            rel="noopener noreferrer"
          >Open ↗</a>
          <button
            type="button"
            class="primary apply"
            :disabled="alreadyApplied(job) || busy.has(job.id)"
            @click="markApplied(job)"
          >
            {{ alreadyApplied(job) ? 'Applied' : 'Mark applied' }}
          </button>
          <button type="button" class="dismiss" @click="dismiss(job.id)">Dismiss</button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.count { color: var(--muted); margin: 0 0 0.75rem; }
.empty { color: var(--muted); }
.error { color: var(--warn); }
.cards { list-style: none; margin: 0; padding: 0; }
.card { border-bottom: 1px solid var(--border); padding: 0.9rem 0; }
.card.closed { opacity: 0.6; }
.head { font-weight: 600; display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.35rem; }
.sep { color: var(--muted); font-weight: 400; }
.status, .stale { font-size: 0.75rem; font-weight: 500; border-radius: 999px; padding: 0.05rem 0.5rem; border: 1px solid currentColor; }
.status { color: var(--ok); }
.stale { color: var(--warn); }
.meta { color: var(--muted); font-size: 0.9rem; }
.reason { margin: 0.35rem 0; }
.skills { list-style: none; padding: 0; margin: 0.35rem 0; display: flex; flex-wrap: wrap; gap: 0.3rem; }
.skills li { font-size: 0.8rem; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 0 0.4rem; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-top: 0.5rem; }
.open { text-decoration: none; border: 1px solid var(--border); border-radius: 6px; padding: 0.3rem 0.7rem; background: var(--surface); }
button.link { border: none; background: none; padding: 0; color: var(--accent); text-decoration: underline; }
</style>
