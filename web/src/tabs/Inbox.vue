<script setup>
// The accepted queue for the selected run (PRD 8.5, M7-T3): one card per role,
// with the three things you do to it - open it, mark it applied, or dismiss it.
// Status is written to the server; Dismiss is local to this session (Q2).
// The run selector lives here, with the list it controls (M12-T1).
import { computed, ref } from 'vue'
import { describeError, setApplicationStatus } from '../api.js'
import { dismiss, isDismissed, restoreAll } from '../dismissed.js'
import { plural, safeUrl, shortDate } from '../format.js'
import { tabEmits, tabProps } from '../shell.js'
import RunSelector from '../components/RunSelector.vue'
import TabLoading from '../components/TabLoading.vue'

const props = defineProps(tabProps)
const emit = defineEmits(tabEmits)

const busy = ref(new Set())
const writeError = ref('')

const visible = computed(() => props.jobs.filter(j => !isDismissed(j.id)))
const hidden = computed(() => props.jobs.filter(j => isDismissed(j.id)))
const firstLoad = computed(() => props.loading && !props.jobs.length)

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
  writeError.value = ''
  busy.value = new Set(busy.value).add(job.id)
  try {
    await setApplicationStatus(job.id, 'applied', {
      company: job.company, role: job.title, url: job.url,
    })
    emit('changed')
  } catch (e) {
    writeError.value = `Could not mark ${job.company} · ${job.title} applied: ${describeError(e)}`
  } finally {
    const next = new Set(busy.value)
    next.delete(job.id)
    busy.value = next
  }
}
</script>

<template>
  <section class="inbox" :aria-busy="loading ? 'true' : 'false'">
    <div class="toolbar">
      <RunSelector :runs="runs" :model-value="run" @update:model-value="v => emit('select-run', v)" />
      <p v-if="!firstLoad && !error" class="count">
        {{ plural(visible.length, 'role') }}
        <template v-if="hidden.length">
          · {{ hidden.length }} dismissed this session
          <button type="button" class="link" @click="restoreAll(hidden.map(j => j.id))">show</button>
        </template>
      </p>
    </div>

    <p v-if="writeError" class="notice error" role="alert">{{ writeError }}</p>

    <div v-if="error" class="notice error" role="alert">
      <p>Could not load the shortlist: {{ error }}</p>
      <button type="button" @click="emit('changed')">Try again</button>
    </div>
    <TabLoading v-else-if="firstLoad" :rows="3" />
    <div v-else-if="!jobs.length" class="empty">
      <p class="empty-title">No roles in this run.</p>
      <p class="muted">Pick another run above, or start a new one from the Runs tab.</p>
    </div>
    <div v-else-if="!visible.length" class="empty">
      <p class="empty-title">Everything here is dismissed for this session.</p>
    </div>

    <ul v-if="!error && visible.length" class="cards" :class="{ refreshing: loading }">
      <li v-for="job in visible" :key="job.id" class="card" :class="{ closed: job.closed }">
        <div class="head">
          <span class="company">{{ job.company }}</span>
          <span class="sep" aria-hidden="true">·</span>
          <span class="title">{{ job.title }}</span>
          <span v-if="job.status" class="status pill" :data-status="job.status">{{ job.status }}</span>
          <span v-if="job.closed" class="stale pill" title="The posting has been taken down">closed</span>
        </div>
        <div class="meta">{{ meta(job) }}</div>
        <p v-if="job.reason" class="reason">{{ job.reason }}</p>
        <ul v-if="job.matched_skills && job.matched_skills.length" class="skills" aria-label="Matched skills">
          <li v-for="skill in job.matched_skills" :key="skill">{{ skill }}</li>
        </ul>
        <div class="actions">
          <a
            v-if="safeUrl(job.url)"
            class="open button"
            :href="safeUrl(job.url)"
            target="_blank"
            rel="noopener noreferrer"
          >Open ↗<span class="visually-hidden"> {{ job.company }} {{ job.title }} (new tab)</span></a>
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
.toolbar {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: var(--space-2) var(--space-4); margin-bottom: var(--space-4);
  min-height: var(--control-h);
}
.count { color: var(--muted); margin: 0; font-size: var(--text-sm); }

/* Roles read like ledger lines: ruled, not boxed. */
.cards {
  list-style: none; margin: 0; padding: 0;
  border-top: 1px solid var(--border);
  transition: opacity 0.15s;
}
.cards.refreshing { opacity: 0.55; }
.card { border-bottom: 1px solid var(--border); padding: var(--space-4) 0; }
.card.closed .head, .card.closed .meta, .card.closed .reason { opacity: 0.6; }
.head { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-1) var(--space-2); font-size: var(--text-md); }
.company { font-weight: 700; }
.title { font-weight: 500; }
.sep { color: var(--muted); }
.stale { color: var(--warn); }
.meta { color: var(--muted); font-size: var(--text-sm); margin-top: var(--space-1); }
/* The judge's reason: the one line that says why this role is here. */
.reason {
  margin: var(--space-2) 0 0;
  padding-left: var(--space-3);
  border-left: 2px solid var(--border-strong);
  font-size: var(--text-sm);
  max-width: 68ch;
}
.skills { list-style: none; padding: 0; margin: var(--space-2) 0 0; display: flex; flex-wrap: wrap; gap: var(--space-1); }
.skills li {
  font-family: var(--mono); font-size: var(--text-xs);
  background: var(--surface-2); border-radius: var(--radius-sm); padding: 0.1rem var(--space-2);
}
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); margin-top: var(--space-3); }
.dismiss { color: var(--muted); }
</style>
