<script setup>
// The resume and what the engine made of it (M12-T3). Upload a new resume
// (drop it or pick it), and the tab stores it with PUT /api/resume, then starts
// the profile refresh and shows its progress (M11-T4). Below that, the current
// derived profile: summary, skills, target titles, interests, version, source.
//
// Only PDF and DOCX get as far as the network; anything else is refused here
// with a reason. The server checks again (type, size, magic bytes) and its
// answer is shown in words, not as a status code alone.
//
// Two views (Q-30, D-74): "Resume and titles" (all of the above) and
// "Application details" (the applicant form and the questions employers asked).
// The view last chosen is remembered; a first visit opens Application details
// when something there needs the owner, and its label carries that count.
// Q-100 A6: the hash can name the view (`#/profile/resume`, `#/profile/details`,
// route.js `useView`) and then wins; the remembered view is the fallback when
// the hash names none.
//
// Q-73: what the resume gave is a readable card ("What we read from your
// resume"), not the job's log; the log sits under a collapsed Details (open
// when the job failed). Q-44: below the card, "Update your application details"
// offers the resume's entries and skills for the applicant profile.
import { computed, nextTick, onActivated, onMounted, ref } from 'vue'
import {
  ApiError, RESUME_TYPES, describeError, failureText, getApplicant, getProfile, getQuestions,
  startProfileRefresh, uploadResume,
} from '../api.js'
import { useJob } from '../composables/useJob.js'
import { exactTime, when } from '../format.js'
import { PROFILE_VIEW_KEY } from '../profileView.js'
import { parseHash, useView } from '../route.js'
import { tabEmits, tabProps } from '../shell.js'
import ApplicationDetails from '../components/ApplicationDetails.vue'
import JobStatus from '../components/JobStatus.vue'
import ResumeRefresh from '../components/ResumeRefresh.vue'
import TitleEditor from '../components/TitleEditor.vue'
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
const refreshRound = ref(0)       // ResumeRefresh looks again after each profile job

const { job, error: jobError, running, refresh, track } = useJob({
  kind: 'profile',
  onFinish: async finished => {
    if (finished.state !== 'succeeded') {
      problem.value = failureText(finished, 'The profile refresh failed - its log is below.')
    }
    await loadProfile()
    if (finished.state === 'succeeded') note.value = readNote()
    refreshRound.value++
  },
})

// ---- the summary card (Q-73) ----
const SKILL_CHIPS = 12
const allSkills = ref(false)
const shownSkills = computed(() => {
  const s = profile.value?.skills ?? []
  return allSkills.value ? s : s.slice(0, SKILL_CHIPS)
})
const moreSkills = computed(() => Math.max(0, (profile.value?.skills?.length ?? 0) - SKILL_CHIPS))
const count = (n, one, many) => `${n} ${n === 1 ? one : many}`
const experienceText = computed(() => {
  const y = profile.value?.years_experience
  if (y === null || y === undefined) return ''
  return y === 0 ? 'Less than a year' : count(y, 'year', 'years')
})
const graduationYear = computed(() => (/^(\d{4})/.exec(String(profile.value?.graduation ?? '')) || [])[1] || '')
function readNote() {
  const p = profile.value
  if (!p?.present) return 'Profile refreshed.'
  return `Resume read: ${count(p.skills?.length ?? 0, 'skill', 'skills')}, ${count(p.target_titles?.length ?? 0, 'job title', 'job titles')}.`
}
// The profile job could not reach the model for the application-details check
// (cli.SKIP_MODEL_DOWN): the panel says so instead of offering nothing.
const modelDown = computed(() => (job.value?.log ?? []).some(l => String(l).includes("application details check skipped: the AI model isn't running")))
const jobFailed = computed(() => !!job.value && job.value.state === 'failed')

// ---- which view: Resume and titles, or Application details ----
const VIEW_KEY = PROFILE_VIEW_KEY
const VIEWS = [
  { id: 'resume', label: 'Resume and titles' },
  { id: 'details', label: 'Application details' },
]
function rememberedView() {
  try {
    const v = window.localStorage.getItem(VIEW_KEY)
    return VIEWS.some(x => x.id === v) ? v : null
  } catch {
    return null
  }
}
const stored = rememberedView()
// A view named in the hash (a deep link from the setup checklist, say) counts as chosen.
const linked = VIEWS.some(v => v.id === parseHash(window.location.hash, ['profile']).view)
const view = useView('profile', VIEWS, stored ?? 'resume')
let chosen = stored !== null || linked  // the owner picked a view, now or before
const counts = ref({ missing: 0, questions: 0 })
const todo = computed(() => counts.value.missing + counts.value.questions)
const labelOf = v => (v.id === 'details' && todo.value > 0 ? `${v.label} (${todo.value})` : v.label)

function pickView(id) {
  view.value = id
  chosen = true
  try { window.localStorage.setItem(VIEW_KEY, id) } catch { /* private window */ }
}

// Application details asks for another view ("Upload in Resume and titles",
// Q71-16): switch, and put the focus on that view's tab so the move is heard.
async function goView(id) {
  if (!VIEWS.some(v => v.id === id)) return
  pickView(id)
  await nextTick()
  document.getElementById(`profile-tab-${id}`)?.focus()
}

function onViewKey(e, i) {
  const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: VIEWS.length - 1 }[e.key]
  if (next === undefined) return
  e.preventDefault()
  const v = VIEWS[(next + VIEWS.length) % VIEWS.length]
  pickView(v.id)
  document.getElementById(`profile-tab-${v.id}`)?.focus()
}

// The Application details view reports its own counts once it is open. Before
// that, a quiet look at the server tells the label (and a first visit) what is
// waiting: a server without these routes simply shows no count.
async function probeCounts() {
  const [form, asked] = await Promise.allSettled([getApplicant(), getQuestions('open')])
  const missing = form.status === 'fulfilled' ? (form.value?.missing?.length ?? 0) : 0
  const questions = asked.status === 'fulfilled'
    ? (asked.value?.groups ?? []).filter(g => !g.status || g.status === 'open').length
    : 0
  setCounts({ missing, questions })
}
function setCounts(c) {
  // `questions: null` = the questions list has not reported; keep what was known.
  counts.value = { missing: c.missing, questions: c.questions ?? counts.value.questions }
  if (!chosen && view.value === 'resume' && todo.value > 0) view.value = 'details'
}

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

// Another tab may have chosen the view while this one was kept alive (Q-76: a
// "Needs your input" attempt opens Application details).
onActivated(() => {
  const v = rememberedView()
  if (v && v !== view.value) { view.value = v; chosen = true }
})

onMounted(() => Promise.all([loadProfile(), refresh(), ...(view.value === 'resume' ? [probeCounts()] : [])]))
</script>

<template>
  <section class="profile-tab">
    <header class="page-head">
      <div>
        <h2 class="page-title">Profile</h2>
        <p v-if="view === 'resume'" class="page-sub">Your resume, and the job titles each run searches for.</p>
        <p v-else class="page-sub">What auto-apply fills into application forms, and the questions it still needs you to answer.</p>
      </div>
      <div class="views" role="tablist" aria-label="Profile sections">
        <button
          v-for="(v, i) in VIEWS"
          :id="`profile-tab-${v.id}`"
          :key="v.id"
          type="button"
          role="tab"
          class="view-tab"
          :class="[`view-${v.id}`, { active: view === v.id }]"
          :aria-selected="view === v.id ? 'true' : 'false'"
          :aria-controls="`profile-panel-${v.id}`"
          :tabindex="view === v.id ? 0 : -1"
          @click="pickView(v.id)"
          @keydown="onViewKey($event, i)"
        >{{ labelOf(v) }}</button>
      </div>
    </header>

    <div
      v-if="view === 'resume'"
      id="profile-panel-resume"
      role="tabpanel"
      aria-labelledby="profile-tab-resume"
    >
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

      <p v-if="running" class="muted reading" role="status">Reading your resume…</p>
      <details v-if="showJob" class="job job-details" :open="jobFailed">
        <summary>Details</summary>
        <JobStatus :job="job" title="Profile refresh log" />
      </details>
      <p v-else-if="jobError" class="notice error" role="alert">Could not read the current job: {{ jobError }}</p>

      <h2 class="section-title">What we read from your resume</h2>
      <TabLoading v-if="loadingProfile" :rows="2" />
      <div v-else-if="profileError" class="notice error" role="alert">
        <p>Could not load the profile: {{ profileError }}</p>
        <button type="button" @click="loadProfile">Try again</button>
      </div>
      <div v-else-if="!profile?.present" class="empty">
        <p class="empty-title">No profile yet.</p>
        <p class="muted">Upload your resume above and the profile is derived from it.</p>
      </div>
      <article v-else class="profile resume-card">
        <ul class="card-lines">
          <li class="read-line"><span class="source">{{ profile.source_file || 'Your resume' }}</span><template v-if="when(profile.parsed_at)"> · read <span class="parsed" :title="exactTime(profile.parsed_at)">{{ when(profile.parsed_at) }}</span></template></li>
          <li v-if="experienceText" class="experience">Experience: {{ experienceText }}</li>
          <li v-if="graduationYear" class="graduation">Graduation: {{ graduationYear }}</li>
          <li class="skill-count">{{ count(profile.skills?.length ?? 0, 'skill', 'skills') }}</li>
        </ul>
        <ul v-if="profile.skills?.length" class="chips skills">
          <li v-for="s in shownSkills" :key="s">{{ s }}</li>
        </ul>
        <button v-if="moreSkills && !allSkills" type="button" class="link more-skills" @click="allSkills = true">and {{ moreSkills }} more</button>
        <p class="title-count">{{ count(profile.target_titles?.length ?? 0, 'job title', 'job titles') }}</p>
        <ul v-if="profile.target_titles?.length" class="titles">
          <li v-for="t in profile.target_titles" :key="t">{{ t }}</li>
        </ul>
        <p v-if="profile.summary" class="summary">{{ profile.summary }}</p>

        <h3>Interests</h3>
        <ul v-if="profile.interests?.length" class="chips interests">
          <li v-for="i in profile.interests" :key="i">{{ i }}</li>
        </ul>
        <p v-else class="muted">None set. They live in config.yaml under judge.interests.</p>
        <p class="muted fine-print">Profile version <span class="version">{{ profile.profile_version }}</span><template v-if="profile.parsed_by"> · read by <span class="parsed-by">{{ profile.parsed_by }}</span></template></p>
      </article>

      <ResumeRefresh :reload="refreshRound" :unavailable="modelDown" @go-view="goView" />

      <h2 class="section-title">Job titles</h2>
      <TitleEditor />
    </div>
    <div
      v-else
      id="profile-panel-details"
      role="tabpanel"
      aria-labelledby="profile-tab-details"
    >
      <ApplicationDetails @counts="setCounts" @go-view="goView" />
    </div>
  </section>
</template>

<style scoped>
.views {
  display: inline-flex; gap: 2px; padding: 2px;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius);
}
.view-tab {
  border: 1px solid transparent; background: transparent; box-shadow: none; color: var(--text-2);
  border-radius: calc(var(--radius) - 2px);
}
.view-tab:hover:not(:disabled) { background: var(--surface); color: var(--text); }
.view-tab.active, .view-tab.active:hover:not(:disabled) {
  background: var(--surface); border-color: var(--border-strong); box-shadow: var(--shadow-sm);
  color: var(--text); font-weight: 650;
}
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
.job-details > summary { cursor: pointer; font-size: var(--text-sm); color: var(--text-2); margin-bottom: var(--space-2); }
.reading { margin: 0 0 var(--space-2); }
.resume-card {
  padding: var(--space-4); border: 1px solid var(--border); border-radius: var(--radius-lg);
  background: var(--surface); overflow-wrap: anywhere; min-width: 0;
}
.card-lines { list-style: none; margin: 0 0 var(--space-2); padding: 0; display: grid; gap: var(--space-1); }
.read-line .source { font-weight: 600; }
.more-skills { margin-top: var(--space-1); padding: 0; font-size: var(--text-sm); }
.title-count { margin: var(--space-3) 0 var(--space-1); }
.fine-print { font-size: var(--text-xs); margin: var(--space-4) 0 0; }
.summary { margin: var(--space-4) 0 0; max-width: 68ch; }
h3 { font-size: var(--text-sm); margin: var(--space-5) 0 var(--space-2); font-weight: 600; }
.chips { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: var(--space-1); }
.chips li {
  font-family: var(--mono); font-size: var(--text-xs);
  background: var(--surface-2); border-radius: var(--radius-sm); padding: 0.15rem var(--space-2);
}
.titles { margin: 0; padding-left: var(--space-5); font-size: var(--text-sm); }
</style>
