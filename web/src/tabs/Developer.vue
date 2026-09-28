<script setup>
// The developer's console (M16): whatever the server is running in the
// background - a run, a profile refresh, title recommendations or a company
// search - with its live log and Cancel. It was the Runs tab's "Current job"
// section; it lives here because only the owner of this install needs the log.
// With accounts (the multi-user PRD) this becomes an admin-only tab.
import { computed, ref } from 'vue'
import { ApiError, cancelJob, describeError } from '../api.js'
import { useJob } from '../composables/useJob.js'
import { tabEmits, tabProps } from '../shell.js'
import JobStatus from '../components/JobStatus.vue'

defineProps(tabProps)
const emit = defineEmits(tabEmits)

const cancelling = ref(false)
const actionError = ref('')
const ready = ref(false)

const { job, error: jobError, running, refresh, track } = useJob({
  // Any kind: a run ending here still refreshes the Inbox and the run list.
  onFinish: finished => emit('changed', { runs: finished.kind === 'run' }),
})

const KIND = { run: 'run', profile: 'profile refresh', titles: 'title recommendation', companies: 'company search' }
const kindLabel = computed(() => KIND[job.value?.kind] ?? 'job')

const ORPHANED = 'This job cannot be cancelled from here: it was started before the web app last '
  + 'restarted, so the web app no longer controls it. It shows as running until it ends. To stop '
  + 'it sooner, end its "python -m jobscraper" process on this machine.'

async function cancel() {
  actionError.value = ''
  cancelling.value = true
  try {
    track(await cancelJob())
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      await refresh()
      actionError.value = running.value ? ORPHANED : 'Nothing is running any more.'
    } else {
      actionError.value = `Could not cancel: ${describeError(e)}`
      refresh()
    }
  } finally {
    cancelling.value = false
  }
}

refresh().finally(() => { ready.value = true })
</script>

<template>
  <section class="developer">
    <header class="page-head">
      <div>
        <h2 class="page-title">Developer</h2>
        <p class="page-sub">The server's background job and its log. Only you see this tab.</p>
      </div>
      <div v-if="running" class="page-controls">
        <button type="button" class="cancel" :disabled="cancelling" @click="cancel">
          {{ cancelling ? 'Cancelling…' : `Cancel ${kindLabel}` }}
        </button>
      </div>
    </header>

    <p v-if="actionError" class="notice error" role="alert">{{ actionError }}</p>

    <h3 class="section-title">Current job</h3>
    <p v-if="!ready" class="muted">Loading…</p>
    <p v-else-if="jobError && !job" class="notice error" role="alert">Could not read the current job: {{ jobError }}</p>
    <div v-else class="console surface">
      <JobStatus :job="job" title="Job log" />
    </div>
  </section>
</template>

<style scoped>
.console { padding: var(--space-4); }
.cancel { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, var(--border-strong)); }
</style>
