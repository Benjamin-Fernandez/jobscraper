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
import { useJob } from '../job.js'
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
.section-title { font-size: 0.95rem; margin: 1.5rem 0 0.6rem; }
.section-title:first-child { margin-top: 0; }
.drop {
  display: grid; gap: 0.25rem; justify-items: center; text-align: center;
  padding: 1.75rem 1rem; border: 2px dashed var(--border); border-radius: 8px;
  background: var(--surface); cursor: pointer;
}
.drop:focus-within { outline: 2px solid var(--accent); outline-offset: 2px; }
.drop.dragging { border-color: var(--accent); }
.drop.disabled { opacity: 0.6; cursor: default; }
.drop-title { font-weight: 600; }
.buttons { margin: 0.75rem 0 1rem; }
.notice.ok { color: var(--ok); }
.job { margin-bottom: 1rem; }
.facts { display: flex; flex-wrap: wrap; gap: 0.5rem 2rem; margin: 0 0 0.75rem; }
.facts dt { font-size: 0.8rem; color: var(--muted); }
.facts dd { margin: 0; }
.summary { margin: 0 0 1rem; }
h3 { font-size: 0.85rem; margin: 1rem 0 0.4rem; color: var(--muted); font-weight: 500; }
.chips { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 0.35rem; }
.chips li { font-size: 0.85rem; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 0.05rem 0.5rem; }
.titles { margin: 0; padding-left: 1.2rem; }
</style>
