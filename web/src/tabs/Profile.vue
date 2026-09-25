<script setup>
// The resume and what the engine made of it (M12-T3). Upload a new resume
// (drop it or pick it), and the tab stores it with PUT /api/resume, then starts
// the profile refresh and shows its progress (M11-T4). Below that, the current
// derived profile: summary, skills, target titles, interests, version, source.
//
// Only PDF and DOCX get as far as the network; anything else is refused here
// with a reason. The server checks again (type, size, magic bytes) and its
// answer is shown in words, not as a status code alone.
import { computed, onMounted, ref } from 'vue'
import {
  ApiError, RESUME_TYPES, describeError, getProfile, startProfileRefresh, uploadResume,
} from '../api.js'
import { useJob } from '../composables/useJob.js'
import { when } from '../format.js'
import { tabEmits, tabProps } from '../shell.js'
import JobStatus from '../components/JobStatus.vue'
import TabLoading from '../components/TabLoading.vue'

defineProps(tabProps)
defineEmits(tabEmits)

const MAX_BYTES = 5 * 1024 * 1024
const ACCEPT = ['.pdf', '.docx', ...Object.values(RESUME_TYPES)].join(',')

const profile = ref(null)
const profileError = ref('')
const loadingProfile = ref(true)
const dragging = ref(false)
const uploading = ref(false)
const refreshing = ref(false)
const problem = ref('')
const note = ref('')

const { job, error: jobError, running, refresh, track } = useJob({
  kind: 'profile',
  onFinish: finished => {
    if (finished.state === 'succeeded') note.value = 'Profile refreshed.'
    else problem.value = 'The profile refresh failed - its log is below.'
    loadProfile()
  },
})

const busy = computed(() => uploading.value || refreshing.value || running.value)
const showJob = computed(() => job.value && job.value.state !== 'idle' && (job.value.kind === 'profile' || running.value))

async function loadProfile() {
  profileError.value = ''
  try {
    profile.value = await getProfile()
  } catch (e) {
    profileError.value = describeError(e)
  } finally {
    loadingProfile.value = false
  }
}

function extension(name) {
  return (/\.([a-z0-9]+)$/i.exec(name || '')?.[1] || '').toLowerCase()
}

// Why a file cannot be used, or '' if it can.
function refusal(file) {
  const ext = extension(file.name)
  const typeOk = Object.values(RESUME_TYPES).includes(file.type)
  if (!(ext in RESUME_TYPES) && !typeOk) {
    return `${file.name} is not a PDF or DOCX file. Save your resume as one of those and try again.`
  }
  if (file.size === 0) return `${file.name} is empty.`
  if (file.size > MAX_BYTES) return `${file.name} is larger than 5 MB.`
  return ''
}

function serverRefusal(e) {
  if (e instanceof ApiError && e.status === 413) return 'The server refused the file: it is larger than 5 MB.'
  if (e instanceof ApiError && e.status === 415) {
    return 'The server refused the file: it is not a readable PDF or DOCX. If it opens fine on your computer, export it again as PDF.'
  }
  return `Could not upload the resume: ${describeError(e)}`
}

async function startRefresh() {
  refreshing.value = true
  try {
    track(await startProfileRefresh(), { started: true })
  } catch (e) {
    problem.value = e instanceof ApiError && e.status === 409
      ? 'A job is already running. Refresh the profile when it has finished.'
      : `Could not start the profile refresh: ${describeError(e)}`
    refresh()
  } finally {
    refreshing.value = false
  }
}

async function take(file) {
  problem.value = ''
  note.value = ''
  if (!file) return
  const why = refusal(file)
  if (why) {
    problem.value = why
    return
  }
  uploading.value = true
  try {
    const saved = await uploadResume(file)
    note.value = `Saved ${file.name} as ${saved.saved} (${Math.max(1, Math.round(saved.bytes / 1024))} KB). Refreshing the profile…`
  } catch (e) {
    problem.value = serverRefusal(e)
    return
  } finally {
    uploading.value = false
  }
  await startRefresh()
}

function onPick(event) {
  const file = event.target.files?.[0]
  event.target.value = '' // picking the same file again still counts
  take(file)
}

function onDrop(event) {
  dragging.value = false
  if (busy.value) return
  take(event.dataTransfer?.files?.[0])
}

function refreshOnly() {
  problem.value = ''
  note.value = ''
  startRefresh()
}

onMounted(() => Promise.all([loadProfile(), refresh()]))
</script>

<template>
  <section class="profile-tab">
    <h2 class="section-title">Resume</h2>
    <label
      class="drop"
      :class="{ dragging, disabled: busy }"
      @dragenter.prevent="dragging = !busy"
      @dragover.prevent="dragging = !busy"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <input
        class="visually-hidden file"
        type="file"
        :accept="ACCEPT"
        :disabled="busy"
        aria-describedby="resume-hint"
        @change="onPick"
      >
      <span class="drop-title">{{ uploading ? 'Uploading…' : 'Drop your resume here, or choose a file' }}</span>
      <span id="resume-hint" class="muted">PDF or DOCX, up to 5 MB. It replaces the resume the profile is built from.</span>
    </label>
    <div class="buttons">
      <button type="button" class="refresh" :disabled="busy" @click="refreshOnly">Re-derive profile from the stored resume</button>
    </div>

    <p v-if="problem" class="notice error" role="alert">{{ problem }}</p>
    <p v-if="note" class="notice ok" role="status">{{ note }}</p>

    <div v-if="showJob" class="job">
      <JobStatus :job="job" title="Profile refresh log" />
    </div>
    <p v-else-if="jobError" class="notice error" role="alert">Could not read the current job: {{ jobError }}</p>

    <h2 class="section-title">Current profile</h2>
    <TabLoading v-if="loadingProfile" :rows="2" />
    <div v-else-if="profileError" class="notice error" role="alert">
      <p>Could not load the profile: {{ profileError }}</p>
      <button type="button" @click="loadProfile">Try again</button>
    </div>
    <div v-else-if="!profile?.present" class="empty">
      <p class="empty-title">No profile yet.</p>
      <p class="muted">Upload your resume above and the profile is derived from it.</p>
    </div>
    <article v-else class="profile">
      <dl class="facts">
        <div><dt>Version</dt><dd class="version">{{ profile.profile_version }}</dd></div>
        <div><dt>Source</dt><dd class="source">{{ profile.source_file || '—' }}</dd></div>
        <div><dt>Derived</dt><dd class="parsed">{{ when(profile.parsed_at) || '—' }}</dd></div>
      </dl>
      <p v-if="profile.summary" class="summary">{{ profile.summary }}</p>

      <h3>Skills</h3>
      <ul v-if="profile.skills?.length" class="chips skills">
        <li v-for="s in profile.skills" :key="s">{{ s }}</li>
      </ul>
      <p v-else class="muted">None found.</p>

      <h3>Target titles</h3>
      <ul v-if="profile.target_titles?.length" class="titles">
        <li v-for="t in profile.target_titles" :key="t">{{ t }}</li>
      </ul>
      <p v-else class="muted">None found.</p>

      <h3>Interests</h3>
      <ul v-if="profile.interests?.length" class="chips interests">
        <li v-for="i in profile.interests" :key="i">{{ i }}</li>
      </ul>
      <p v-else class="muted">None set. They live in config.yaml under judge.interests.</p>
    </article>
  </section>
</template>

<style scoped>
.drop {
  display: grid; gap: var(--space-1); justify-items: center; text-align: center;
  padding: var(--space-6) var(--space-4);
  border: 2px dashed var(--border-strong); border-radius: var(--radius-lg);
  background: var(--surface); cursor: pointer;
  transition: border-color 0.12s, background-color 0.12s;
}
.drop:hover { border-color: var(--accent); }
.drop:focus-within { outline: 2px solid var(--focus); outline-offset: 2px; }
.drop.dragging { border-color: var(--accent); background: var(--accent-soft); }
.drop.disabled { opacity: 0.6; cursor: not-allowed; }
.drop.disabled:hover { border-color: var(--border-strong); }
.drop-title { font-weight: 600; }
.drop .muted { font-size: var(--text-sm); }
.buttons { margin: var(--space-3) 0 var(--space-4); }
.job { margin-bottom: var(--space-4); }
.facts {
  display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-6);
  margin: 0 0 var(--space-4); padding-bottom: var(--space-3); border-bottom: 1px solid var(--border);
}
.facts dt { font-size: var(--text-xs); color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.facts dd { margin: 0; font-family: var(--mono); font-size: var(--text-sm); }
.summary { margin: 0 0 var(--space-4); max-width: 68ch; }
h3 { font-size: var(--text-sm); margin: var(--space-5) 0 var(--space-2); font-weight: 600; }
.chips { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: var(--space-1); }
.chips li {
  font-family: var(--mono); font-size: var(--text-xs);
  background: var(--surface-2); border-radius: var(--radius-sm); padding: 0.15rem var(--space-2);
}
.titles { margin: 0; padding-left: var(--space-5); font-size: var(--text-sm); }
</style>
