<script setup>
// Settings → Apply (Q-100 design §4.3): how applying works right now, in rows. Mode and
// readiness come from GET /api/apply/status and GET /api/applicant (both on the server
// today); limits, the human-check wait and cover letters come from GET /api/apply/settings
// (Q-111), which may not exist yet. A row whose source is absent is hidden, never faked.
//
// Read-only unless the server says `writable: true`. The page never sends a probe PUT:
// that would pin `apply.*` rows over config.yaml (design §4.3, config.py:162-172). A save
// that comes back 404, 405 or 422 shows "Couldn't save: {detail}" and puts the controls
// back to read-only. Switching to automatic asks first.
//
// The Application mailbox row makes the hint "Set up the mailbox in Settings → Apply"
// (apply/contracts.py:175) true: it shows the mailbox's state and links to Accounts.
// JobScraper waits for the owner at a human check; it never solves one.
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError, describeError } from '../api.js'
import { findItem } from '../applicantForm.js'
import { COPY } from '../connections.js'
import { getApplicantSummary, getApplySettings, getApplyStatus, putApplySettings } from '../connections_api.js'
import StateChip from './StateChip.vue'
import TabLoading from './TabLoading.vue'

const props = defineProps({
  // The GET /api/connections answer Settings holds, or null.
  connections: { type: Object, default: null },
})

const loading = ref(true)
const status = ref(null)       // { mode, missing, busy } or null
const settings = ref(null)     // Q-111's answer or null
const summary = ref(null)      // { missing, completeness, form } or null

async function quiet(call) {
  try { return await call() } catch { return null }
}

async function load() {
  loading.value = true
  ;[status.value, settings.value, summary.value] = await Promise.all([
    quiet(getApplyStatus), quiet(getApplySettings), quiet(getApplicantSummary),
  ])
  loading.value = false
}
onMounted(load)

// ---- read rows ----
const mode = computed(() => settings.value?.mode ?? status.value?.mode ?? null)
const modeText = computed(() => (mode.value === 'auto' ? COPY.modeAuto : COPY.modeDryRun))

const limits = computed(() => {
  const s = settings.value
  if (!s || s.daily_cap === undefined) return ''
  const parts = [
    `${s.daily_cap} ${s.daily_cap === 1 ? 'application' : 'applications'} a day`,
    `${s.per_employer_daily_cap} per employer`,
    s.headed ? 'browser window shown' : 'browser window hidden',
  ]
  return parts.join(' · ')
})
const humanChecks = computed(() => {
  const s = settings.value
  if (!s || s.captcha_wait_s === undefined) return ''
  return s.captcha_wait_s > 0
    ? `JobScraper waits up to ${s.captcha_wait_s} s for you to finish a human check in the window. It never solves them.`
    : 'JobScraper stops and leaves the page to you. It never solves them.'
})

const mailbox = computed(() => (props.connections?.items ?? []).find(i => i.id === 'apply-mailbox') ?? null)

const labels = computed(() => {
  const form = summary.value?.form
  return (summary.value?.missing ?? []).map(p => (findItem(form, p)?.label || p).toLowerCase())
})
const missingText = computed(() => {
  const shown = [...new Set(labels.value)]
  const n = shown.length
  if (!n) return ''
  const head = shown.slice(0, 4).join(', ')
  return `${n} ${n === 1 ? 'thing' : 'things'} to fill in first: ${head}${n > 4 ? ` and ${n - 4} more` : ''}`
})

const hasCompose = computed(() => typeof settings.value?.compose_enabled === 'boolean')

// ---- editing (only when the server says so) ----
const readOnly = ref(false)
const editable = computed(() => settings.value?.writable === true && !readOnly.value)
const draft = ref(null)
const saving = ref(false)
const saveError = ref('')
const savedNote = ref('')
const confirmAuto = ref(false)

const FIELDS = ['mode', 'daily_cap', 'per_employer_daily_cap', 'headed', 'captcha_wait_s', 'compose_enabled']

function resetDraft() {
  const s = settings.value
  draft.value = s ? Object.fromEntries(FIELDS.filter(k => s[k] !== undefined).map(k => [k, s[k]])) : null
}
// The draft starts from what the server saved, and follows it after a save.
watch(settings, resetDraft, { immediate: true })

function whole(v, lo, hi, what) {
  const n = typeof v === 'number' ? v : Number(v)
  if (v === '' || v === null || !Number.isInteger(n)) return `${what}: enter a whole number.`
  if (n < lo || n > hi) return `${what}: between ${lo} and ${hi}.`
  return ''
}
const problems = computed(() => {
  const d = draft.value
  if (!d) return {}
  const out = {}
  if ('daily_cap' in d) out.daily_cap = whole(d.daily_cap, 1, 50, 'Applications a day')
  if ('per_employer_daily_cap' in d) out.per_employer_daily_cap = whole(d.per_employer_daily_cap, 1, 50, 'Per employer')
  if ('captcha_wait_s' in d) out.captcha_wait_s = whole(d.captcha_wait_s, 0, 600, 'Human-check wait')
  return out
})
const invalid = computed(() => Object.values(problems.value).some(Boolean))
const changes = computed(() => {
  const d = draft.value
  const s = settings.value
  if (!d || !s) return {}
  const out = {}
  for (const k of Object.keys(d)) {
    const v = ['daily_cap', 'per_employer_daily_cap', 'captcha_wait_s'].includes(k) ? Number(d[k]) : d[k]
    if (v !== s[k]) out[k] = v
  }
  return out
})
const unchanged = computed(() => Object.keys(changes.value).length === 0)

function requestSave() {
  if (invalid.value || unchanged.value || saving.value) return
  if (changes.value.mode === 'auto') { confirmAuto.value = true; return }
  send()
}
function keepDryRun() {
  confirmAuto.value = false
  if (draft.value) draft.value.mode = settings.value?.mode ?? 'dry_run'
}

async function send() {
  confirmAuto.value = false
  saving.value = true
  saveError.value = ''
  savedNote.value = ''
  try {
    const next = await putApplySettings(changes.value)
    if (next === null) {
      readOnly.value = true
      saveError.value = "Couldn't save: this server doesn't accept changes yet."
    } else {
      settings.value = next
      savedNote.value = 'Saved.'
      // The mode may have changed what GET /api/apply/status says too.
      status.value = (await quiet(getApplyStatus)) ?? status.value
    }
  } catch (e) {
    if (e instanceof ApiError && [404, 405, 422].includes(e.status)) readOnly.value = true
    saveError.value = `Couldn't save: ${describeError(e)}`
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="apply-settings">
    <h3 class="section-title apply-title">Apply</h3>
    <TabLoading v-if="loading" :rows="3" />

    <template v-else>
      <dl class="apply-rows surface">
        <div v-if="mode" class="apply-row" data-row="mode">
          <dt>Mode</dt>
          <dd>
            <template v-if="editable && draft">
              <div class="mode-options" role="radiogroup" aria-label="Mode">
                <label class="mode-option" :class="{ active: draft.mode === 'dry_run' }">
                  <input v-model="draft.mode" type="radio" class="visually-hidden" value="dry_run" name="apply-mode">
                  <span class="mode-name">Dry run</span>
                  <span class="mode-sub">Fills each form and leaves it open for you. Nothing is sent.</span>
                </label>
                <label class="mode-option" :class="{ active: draft.mode === 'auto' }">
                  <input v-model="draft.mode" type="radio" class="visually-hidden" value="auto" name="apply-mode">
                  <span class="mode-name">Automatic</span>
                  <span class="mode-sub">Sends each application after its final check passes.</span>
                </label>
              </div>
            </template>
            <template v-else>
              <span class="apply-mode-text" :data-mode="mode">{{ modeText }}</span>
            </template>
          </dd>
        </div>

        <div v-if="limits" class="apply-row" data-row="limits">
          <dt>Limits</dt>
          <dd>
            <template v-if="editable && draft">
              <div class="limit-fields">
                <label class="limit-field">
                  <span>Applications a day</span>
                  <input v-model.number="draft.daily_cap" type="number" inputmode="numeric" min="1" max="50" step="1" :aria-invalid="problems.daily_cap ? 'true' : 'false'">
                </label>
                <label class="limit-field">
                  <span>Per employer a day</span>
                  <input v-model.number="draft.per_employer_daily_cap" type="number" inputmode="numeric" min="1" max="50" step="1" :aria-invalid="problems.per_employer_daily_cap ? 'true' : 'false'">
                </label>
                <label class="check-field">
                  <input v-model="draft.headed" type="checkbox">
                  <span>Show the browser window</span>
                </label>
              </div>
              <p v-if="problems.daily_cap" class="apply-problem" role="alert">{{ problems.daily_cap }}</p>
              <p v-if="problems.per_employer_daily_cap" class="apply-problem" role="alert">{{ problems.per_employer_daily_cap }}</p>
            </template>
            <template v-else>{{ limits }}</template>
          </dd>
        </div>

        <div v-if="humanChecks" class="apply-row" data-row="human-checks">
          <dt>Human checks</dt>
          <dd>
            <template v-if="editable && draft">
              <label class="limit-field">
                <span>Seconds JobScraper waits for you (0 to stop at once)</span>
                <input v-model.number="draft.captcha_wait_s" type="number" inputmode="numeric" min="0" max="600" step="1" :aria-invalid="problems.captcha_wait_s ? 'true' : 'false'">
              </label>
              <p v-if="problems.captcha_wait_s" class="apply-problem" role="alert">{{ problems.captcha_wait_s }}</p>
              <p class="apply-sub">JobScraper never solves a human check; it leaves the page to you.</p>
            </template>
            <template v-else>{{ humanChecks }}</template>
          </dd>
        </div>

        <div class="apply-row" data-row="mailbox">
          <dt>Application mailbox</dt>
          <dd class="apply-inline">
            <StateChip v-if="mailbox" :item="mailbox" label="Application mailbox" />
            <a class="apply-link" href="#/settings/accounts/apply-mailbox">Manage in Accounts →</a>
          </dd>
        </div>

        <div v-if="summary" class="apply-row" data-row="ready">
          <dt>Ready to apply</dt>
          <dd>
            <template v-if="missingText">
              <span class="apply-inline">
                <span>{{ missingText }}</span>
                <a class="button apply-cta" href="#/profile/details">Fill in details</a>
              </span>
            </template>
            <template v-else>Ready.</template>
            <p v-if="status?.busy" class="apply-sub">An application is running now.</p>
            <span class="apply-inline apply-sub">
              <span>To apply, open a role in the Inbox and choose Auto-apply.</span>
              <a class="button apply-cta" href="#/inbox">Open Inbox</a>
            </span>
          </dd>
        </div>

        <div v-if="hasCompose" class="apply-row" data-row="compose">
          <dt>Cover letters</dt>
          <dd>
            <label v-if="editable && draft" class="check-field">
              <input v-model="draft.compose_enabled" type="checkbox">
              <span>Write a cover letter when a form requires one</span>
            </label>
            <span v-else>{{ settings.compose_enabled ? 'On. JobScraper writes a cover letter when a form requires one.' : 'Off.' }}</span>
            <p v-if="!(editable && draft ? draft.compose_enabled : settings.compose_enabled)" class="apply-sub">
              Off: JobScraper stops and asks you instead.
            </p>
          </dd>
        </div>
      </dl>

      <div v-if="confirmAuto" class="confirm-auto" role="group" aria-labelledby="confirm-auto-title" @keydown.esc="keepDryRun">
        <p id="confirm-auto-title" class="confirm-title">Send applications automatically?</p>
        <p class="confirm-body">JobScraper sends each one only after its final check passes, within your daily limits.</p>
        <div class="confirm-buttons">
          <button type="button" class="primary confirm-yes" :disabled="saving" @click="send">Switch to automatic</button>
          <button type="button" class="confirm-no" @click="keepDryRun">Keep dry run</button>
        </div>
      </div>

      <div v-if="editable && draft && !confirmAuto" class="apply-save">
        <button type="button" class="primary apply-save-btn" :disabled="invalid || unchanged || saving" @click="requestSave">
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
      <p v-if="saveError" class="notice error apply-error" role="alert">{{ saveError }}</p>
      <p v-if="savedNote" class="notice ok apply-saved" role="status">{{ savedNote }}</p>
    </template>
  </div>
</template>

<style scoped>
.apply-settings { display: grid; gap: var(--space-3); }
.apply-title { margin: 0; }
.apply-rows { display: grid; margin: 0; max-width: 46rem; padding: var(--space-2) var(--space-4); }
.apply-row {
  display: grid; grid-template-columns: 11rem 1fr; gap: var(--space-1) var(--space-4);
  padding: var(--space-3) 0; border-top: 1px solid var(--border); font-size: var(--text-sm);
}
.apply-row:first-child { border-top: 0; }
.apply-row dt { font-weight: 600; color: var(--text-2); }
.apply-row dd { margin: 0; display: grid; gap: var(--space-2); justify-items: start; min-width: 0; text-wrap: pretty; }
.apply-inline { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-3); }
.apply-sub { margin: 0; color: var(--muted); }
.apply-link { display: inline-flex; align-items: center; min-height: 2rem; }
.apply-problem { margin: 0; color: var(--danger); }
.mode-options { display: grid; gap: var(--space-2); width: 100%; }
.mode-option {
  display: grid; gap: 2px; padding: var(--space-2) var(--space-3); cursor: pointer;
  border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface-2);
}
.mode-option.active { background: var(--surface); border-color: var(--accent); box-shadow: var(--shadow-sm); }
.mode-option:has(input:focus-visible) { outline: 2px solid var(--focus); outline-offset: 2px; }
.mode-name { font-weight: 650; }
.mode-sub { color: var(--text-2); }
.limit-fields { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: end; }
.limit-field { display: grid; gap: var(--space-1); font-weight: 600; }
.limit-field input { width: 8rem; }
.check-field { display: inline-flex; align-items: center; gap: var(--space-2); min-height: 2rem; cursor: pointer; font-weight: 600; }
.confirm-auto {
  display: grid; gap: var(--space-2); max-width: 46rem; padding: var(--space-3);
  background: var(--warn-soft); border-radius: var(--radius);
}
.confirm-auto p { margin: 0; font-size: var(--text-sm); }
.confirm-title { font-weight: 650; }
.confirm-buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.apply-error, .apply-saved { margin: 0; max-width: 34rem; }

@media (max-width: 640px) {
  .apply-rows { padding: var(--space-2) var(--space-3); }
  .apply-row { grid-template-columns: 1fr; }
  .apply-link, .check-field { min-height: var(--touch-min); }
  .limit-field input { min-height: var(--touch-min); }
}
</style>
