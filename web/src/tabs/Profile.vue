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
// Q-73: what the resume gave is a readable card, not the job's log; the log
// sits under a collapsed Details (open when the job failed). Q-44: below the
// cards, "Update your application details" offers the resume's entries and
// skills for the applicant profile.
//
// Q-118 LE: once a resume exists the view is a compact "From your resume" card
// (what was read, Replace, Re-read; the file name is not shown and the big drop
// zone is gone - the card itself takes a dropped file), then Skills and Job
// titles as two chip cards side by side. The drop zone shows only before the
// first resume. Skills are read-only: no endpoint edits them.
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
const fileInput = ref(null)       // the hidden picker behind "Replace resume"

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

// ---- the resume card and the skills card (Q-73, Q-118 LE) ----
const SKILL_CHIPS = 12
const SUMMARY_CLAMP_CHARS = 160   // about three lines; a shorter summary has nothing to expand
const allSkills = ref(false)
const summaryOpen = ref(false)
const longSummary = computed(() => String(profile.value?.summary ?? '').length > SUMMARY_CLAMP_CHARS)
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

// A drag moving over the card's own children fires dragleave on the card; only
// leaving the card itself ends the highlight.
function onDragLeave(event) {
  if (event.relatedTarget && event.currentTarget?.contains(event.relatedTarget)) return
  dragging.value = false
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
      <div class="views ui-segmented" role="tablist" aria-label="Profile sections">
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
      class="resume-view"
      role="tabpanel"
      aria-labelledby="profile-tab-resume"
    >
      <!-- Loading: placeholder cards about the height of the real ones. -->
      <div v-if="loadingProfile" class="ui-grid" role="status" aria-busy="true">
        <span class="visually-hidden">Loading your profile…</span>
        <div class="ui-card span-12 sk-card" aria-hidden="true">
          <span class="ui-skeleton sk-title" />
          <span class="ui-skeleton sk-line" />
        </div>
        <div class="ui-card span-6 sk-card" aria-hidden="true">
          <span class="ui-skeleton sk-title" />
          <span class="ui-skeleton sk-block" />
        </div>
        <div class="ui-card span-6 sk-card" aria-hidden="true">
          <span class="ui-skeleton sk-title" />
          <span class="ui-skeleton sk-block" />
        </div>
      </div>

      <div v-else-if="profileError" class="notice error" role="alert">
        <p>Could not load the profile: {{ profileError }}</p>
        <button type="button" @click="loadProfile">Try again</button>
      </div>

      <!-- No resume yet: the drop zone, and what to do. -->
      <template v-else-if="!profile?.present">
        <label
          class="drop ui-drop"
          :class="{ dragging, disabled: busy }"
          :data-drop="dragging ? 'over' : undefined"
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
        <div class="empty">
          <p class="empty-title">No profile yet.</p>
          <p class="muted">Upload your resume above and the profile is derived from it.</p>
          <button type="button" class="refresh" :disabled="busy" @click="refreshOnly">Re-read resume</button>
        </div>
      </template>

      <!-- A resume exists: a compact card, which is also where a dropped file lands. -->
      <section
        v-else
        class="ui-card ui-drop profile resume-card"
        :class="{ dragging }"
        :data-drop="dragging ? 'over' : undefined"
        aria-labelledby="resume-card-title"
        @dragenter.prevent="dragging = !busy"
        @dragover.prevent="dragging = !busy"
        @dragleave.prevent="onDragLeave"
        @drop.prevent="onDrop"
      >
        <header class="ui-card-head">
          <h3 id="resume-card-title" class="ui-card-title">From your resume</h3>
          <span v-if="when(profile.parsed_at)" class="muted read-line">read <span class="parsed" :title="exactTime(profile.parsed_at)">{{ when(profile.parsed_at) }}</span></span>
          <div class="ui-card-actions">
            <input
              ref="fileInput"
              class="visually-hidden file"
              type="file"
              tabindex="-1"
              aria-hidden="true"
              :accept="ACCEPT"
              :disabled="busy"
              @change="onPick"
            >
            <button type="button" class="replace" :disabled="busy" aria-describedby="resume-hint" @click="fileInput?.click()">{{ uploading ? 'Uploading…' : 'Replace resume' }}</button>
            <button
              type="button"
              class="refresh"
              title="Read the stored resume again and rebuild the profile from it"
              :disabled="busy"
              @click="refreshOnly"
            >Re-read resume</button>
          </div>
        </header>
        <dl v-if="experienceText || graduationYear" class="facts">
          <div v-if="experienceText" class="fact experience"><dt>Experience</dt><dd>{{ experienceText }}</dd></div>
          <div v-if="graduationYear" class="fact graduation"><dt>Graduation</dt><dd>{{ graduationYear }}</dd></div>
        </dl>
        <template v-if="profile.summary">
          <p class="summary" :class="{ clamped: longSummary && !summaryOpen }">{{ profile.summary }}</p>
          <button
            v-if="longSummary"
            type="button"
            class="ghost summary-toggle"
            :aria-expanded="summaryOpen ? 'true' : 'false'"
            @click="summaryOpen = !summaryOpen"
          >{{ summaryOpen ? 'Show less' : 'Show more' }}</button>
        </template>
        <p id="resume-hint" class="muted fine-print">PDF or DOCX, up to 5 MB. Profile version <span class="version">{{ profile.profile_version }}</span><template v-if="profile.parsed_by"> · read by <span class="parsed-by">{{ profile.parsed_by }}</span></template></p>
        <span v-if="dragging" class="drop-overlay" aria-hidden="true">Drop to replace your resume</span>
      </section>

      <p v-if="problem" class="notice error msg" role="alert">{{ problem }}</p>
      <p v-if="note" class="notice ok msg" role="status">{{ note }}</p>

      <p v-if="running" class="muted reading" role="status">Reading your resume…</p>
      <details v-if="showJob" class="job job-details" :open="jobFailed">
        <summary>Details</summary>
        <JobStatus :job="job" title="Profile refresh log" />
      </details>
      <p v-else-if="jobError" class="notice error msg" role="alert">Could not read the current job: {{ jobError }}</p>

      <div v-if="!loadingProfile" class="ui-grid cards">
        <section
          v-if="!profileError && profile?.present"
          class="ui-card span-6 skills-card"
          aria-labelledby="skills-card-title"
        >
          <header class="ui-card-head">
            <h3 id="skills-card-title" class="ui-card-title">Skills</h3>
            <span class="ui-count num skill-count">{{ profile.skills?.length ?? 0 }}</span>
          </header>
          <ul v-if="profile.skills?.length" class="chips skills" aria-label="Skills from your resume">
            <li v-for="s in shownSkills" :key="s" class="chip">{{ s }}</li>
          </ul>
          <p v-else class="muted">No skills were found in your resume.</p>
          <button
            v-if="moreSkills"
            type="button"
            class="ghost more-skills"
            :aria-expanded="allSkills ? 'true' : 'false'"
            @click="allSkills = !allSkills"
          >{{ allSkills ? 'Show fewer' : `Show all ${profile.skills.length}` }}</button>

          <div class="interests-group">
            <h4>Interests</h4>
            <ul v-if="profile.interests?.length" class="chips interests" aria-label="Interests">
              <li v-for="i in profile.interests" :key="i" class="chip">{{ i }}</li>
            </ul>
            <p v-else class="muted">None set. They live in config.yaml under judge.interests.</p>
          </div>
          <p class="muted fine-print">From your resume. Re-read it to update them.</p>
        </section>
        <TitleEditor :class="!profileError && profile?.present ? 'span-6' : 'span-12'" />
      </div>

      <ResumeRefresh :reload="refreshRound" :unavailable="modelDown" @go-view="goView" />
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
/* The tablist is a global .ui-segmented; on a phone it takes the full width. */
@media (max-width: 640px) {
  .views { display: flex; width: 100%; }
  .views > button { flex: 1 1 0; min-width: 0; padding: 0 var(--space-2); white-space: normal; line-height: 1.2; }
}
.resume-view > * + * { margin-top: var(--space-5); }
.resume-view > .msg, .resume-view > .reading, .resume-view > .job { margin-top: var(--space-3); }

/* No resume yet: the drop zone. */
.drop {
  display: grid; gap: var(--space-1); justify-items: center; text-align: center;
  padding: var(--space-6) var(--space-4);
  border: 2px dashed var(--border-strong); border-radius: var(--radius-lg);
  background: var(--surface); cursor: pointer;
  transition: border-color var(--motion), background-color var(--motion);
}
.drop:hover { border-color: var(--accent); }
.drop:focus-within { outline: 2px solid var(--focus); outline-offset: 2px; }
.drop.dragging { border-color: var(--accent); background: var(--accent-soft); outline: 0; }
.drop.disabled { opacity: 0.6; cursor: not-allowed; }
.drop.disabled:hover { border-color: var(--border-strong); }
.drop-title { font-weight: var(--weight-semibold); }
.drop .muted { font-size: var(--text-sm); }
.empty .refresh { margin-top: var(--space-3); }
@media (max-width: 640px) {
  .drop { padding: var(--space-5) var(--space-3); }
}

/* The compact resume card. */
.resume-card { position: relative; overflow-wrap: anywhere; }
.resume-card.dragging { border-color: var(--accent); }
.read-line { font-size: var(--text-sm); }
.facts { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-6); margin: 0 0 var(--space-3); }
.fact { display: grid; gap: 2px; }
.fact dt { font-size: var(--text-xs); color: var(--muted); }
.fact dd { margin: 0; font-weight: var(--weight-semibold); }
.summary { margin: 0; max-width: 68ch; color: var(--text-2); }
.summary.clamped {
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; line-clamp: 3; overflow: hidden;
}
.summary-toggle { margin-top: var(--space-1); padding-left: 0; padding-right: var(--space-2); min-height: 0; }
.fine-print { font-size: var(--text-xs); margin: var(--space-3) 0 0; }
.drop-overlay {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  border-radius: inherit; background: var(--accent-soft); color: var(--accent);
  font-weight: var(--weight-semibold); pointer-events: none;
}
.job-details > summary { cursor: pointer; font-size: var(--text-sm); color: var(--text-2); margin-bottom: var(--space-2); }

/* Skills. */
.chips { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: var(--space-2); }
.more-skills { margin-top: var(--space-2); padding-left: 0; min-height: 0; }
.interests-group { margin-top: var(--space-4); padding-top: var(--space-3); border-top: 1px solid var(--border); }
.interests-group h4 { margin: 0 0 var(--space-2); font-size: var(--text-sm); font-weight: var(--weight-semibold); }

/* Loading placeholders. */
.sk-card { display: grid; gap: var(--space-3); }
.sk-title { width: 8rem; height: 1.1rem; }
.sk-line { height: 2.5rem; }
.sk-block { height: 6rem; }
</style>
