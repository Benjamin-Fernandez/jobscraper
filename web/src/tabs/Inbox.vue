<script setup>
// The Inbox (M13-T2): new roles to triage, laid out the way LinkedIn and Indeed
// lay out a job search - a list on the left, the selected role in full on the
// right (one column with a Back button on a phone).
//
// The Inbox holds only roles you have not acted on. Save (status `to_apply`)
// and Mark applied (`applied`) move a role to the Applications tab at once,
// with a toast offering Undo and a link there. Not interested hides it for
// this session only (open question Q2, left as is by the user). Opening the
// posting on the company's site asks afterwards whether you applied, the way
// LinkedIn does, so the record is one click away.
import { computed, nextTick, ref } from 'vue'
import { describeError, setApplicationStatus, untrackApplication } from '../api.js'
import { dismiss, isDismissed, restoreAll } from '../dismissed.js'
import { cleanLocation, plural, safeUrl, shortDate } from '../format.js'
import { tabEmits, tabProps } from '../shell.js'
import { showToast } from '../toast.js'
import CompanyMark from '../components/CompanyMark.vue'
import Icon from '../components/Icon.vue'
import RunSelector from '../components/RunSelector.vue'
import TabLoading from '../components/TabLoading.vue'

const props = defineProps(tabProps)
const emit = defineEmits(tabEmits)

const query = ref('')
const sort = ref('newest')
const selectedId = ref(null)
const detailOpen = ref(false)          // phone layout: the detail replaces the list
const pending = ref(new Set())         // just saved/applied: gone before the reload lands
const opened = ref(new Set())          // postings opened on the company site this session
const busy = ref(false)
const writeError = ref('')

const firstLoad = computed(() => props.loading && !props.jobs.length)

// Untracked roles: no application status yet. Tracked ones live in Applications.
const untracked = computed(() => props.jobs.filter(j => !j.status && !pending.value.has(j.id)))
const tracked = computed(() => props.jobs.filter(j => j.status).length)
const dismissedHere = computed(() => untracked.value.filter(j => isDismissed(j.id)))

function matches(job, q) {
  if (!q) return true
  return [job.title, job.company, job.location].some(v => (v || '').toLowerCase().includes(q))
}

const SORTS = {
  newest: (a, b) => String(b.decided_at || '').localeCompare(String(a.decided_at || '')),
  company: (a, b) => String(a.company || '').localeCompare(String(b.company || ''), undefined, { sensitivity: 'base' }),
}

const visible = computed(() => {
  const q = query.value.trim().toLowerCase()
  return untracked.value
    .filter(j => !isDismissed(j.id) && matches(j, q))
    .sort(SORTS[sort.value] ?? SORTS.newest)
})

const companies = computed(() => new Set(visible.value.map(j => j.company)).size)
const selected = computed(() => visible.value.find(j => j.id === selectedId.value) ?? visible.value[0] ?? null)

function years(job) {
  if (job.yoe_min === null || job.yoe_min === undefined) return null
  return job.yoe_min === 0 ? 'No experience required' : `${plural(job.yoe_min, 'year')} experience`
}

function shortYears(job) {
  if (job.yoe_min === null || job.yoe_min === undefined) return null
  return job.yoe_min === 0 ? 'Entry level' : `${job.yoe_min}+ yrs`
}

function cardMeta(job) {
  return [cleanLocation(job.location), shortYears(job)].filter(Boolean).join(' · ')
}

// ---- selection and the keyboard ----

const itemEls = {}

function select(job, { open = true } = {}) {
  selectedId.value = job.id
  if (open) detailOpen.value = true
}

// The role to show once `job` leaves the list: the next one, else the previous.
function neighbour(job) {
  const list = visible.value
  const i = list.findIndex(j => j.id === job.id)
  return (list[i + 1] ?? list[i - 1] ?? null)?.id ?? null
}

async function onListKey(event) {
  const step = { ArrowDown: 1, j: 1, ArrowUp: -1, k: -1 }[event.key]
  if (!step || !visible.value.length) return
  event.preventDefault()
  const list = visible.value
  const i = Math.max(0, list.findIndex(j => j.id === selected.value?.id))
  const next = list[Math.min(list.length - 1, Math.max(0, i + step))]
  select(next, { open: false })
  await nextTick()
  itemEls[next.id]?.focus()
}

// ---- actions ----

function unpend(id) {
  const next = new Set(pending.value)
  next.delete(id)
  pending.value = next
}

const VERB = { applied: 'Marked applied', to_apply: 'Saved' }

async function track(job, status) {
  writeError.value = ''
  busy.value = true
  const next = neighbour(job)
  pending.value = new Set(pending.value).add(job.id)
  selectedId.value = next
  try {
    await setApplicationStatus(job.id, status, { company: job.company, role: job.title, url: job.url })
    emit('changed')
    showToast({
      message: `${VERB[status]}: ${job.title} at ${job.company}`,
      action: { label: 'Undo', run: () => undo(job) },
      link: { label: 'View in Applications', href: '#/applications' },
    })
  } catch (e) {
    unpend(job.id)
    selectedId.value = job.id
    writeError.value = `Could not update ${job.company} · ${job.title}: ${describeError(e)}`
  } finally {
    busy.value = false
  }
}

async function undo(job) {
  try {
    await untrackApplication(job.id)
  } catch (e) {
    if (e?.status !== 404) {
      writeError.value = `Could not undo ${job.company} · ${job.title}: ${describeError(e)}`
      return
    }
  }
  unpend(job.id)
  selectedId.value = job.id
  emit('changed')
}

function notInterested(job) {
  selectedId.value = neighbour(job)
  dismiss(job.id)
  showToast({
    message: `Hidden for this session: ${job.title} at ${job.company}`,
    action: { label: 'Undo', run: () => { restoreAll([job.id]); selectedId.value = job.id } },
  })
}

function markOpened(job) {
  opened.value = new Set(opened.value).add(job.id)
}
</script>

<template>
  <section class="inbox" :aria-busy="loading ? 'true' : 'false'">
    <header class="page-head">
      <div>
        <h2 class="page-title">Inbox</h2>
        <p v-if="!firstLoad && !error" class="page-sub count">
          {{ plural(visible.length, 'new role') }} at {{ plural(companies, 'company', 'companies') }}
          <template v-if="dismissedHere.length">
            · {{ dismissedHere.length }} hidden this session
            <button type="button" class="link show-hidden" @click="restoreAll(dismissedHere.map(j => j.id))">show</button>
          </template>
          <template v-if="tracked">
            · <a class="tracked" href="#/applications">{{ tracked }} in Applications</a>
          </template>
        </p>
      </div>
      <div class="page-controls">
        <label class="search">
          <Icon name="search" />
          <span class="visually-hidden">Search roles</span>
          <input v-model="query" type="search" placeholder="Search title, company, location">
        </label>
        <label class="sort">
          <span class="visually-hidden">Sort</span>
          <select v-model="sort">
            <option value="newest">Newest first</option>
            <option value="company">Company A–Z</option>
          </select>
        </label>
        <RunSelector :runs="runs" :model-value="run" @update:model-value="v => emit('select-run', v)" />
      </div>
    </header>

    <p v-if="writeError" class="notice error" role="alert">{{ writeError }}</p>

    <div v-if="error" class="notice error" role="alert">
      <p>Could not load the shortlist: {{ error }}</p>
      <button type="button" @click="emit('changed')">Try again</button>
    </div>
    <TabLoading v-else-if="firstLoad" :rows="3" />
    <div v-else-if="!jobs.length" class="empty">
      <Icon name="inbox" :size="28" />
      <p class="empty-title">No roles in this run.</p>
      <p class="muted">Pick another run above, or start a new one from the Runs tab.</p>
    </div>
    <div v-else-if="!untracked.length" class="empty caught-up">
      <Icon name="check" :size="28" />
      <p class="empty-title">You're all caught up.</p>
      <p class="muted">Every role in this run is in <a href="#/applications">Applications</a>.</p>
    </div>
    <div v-else-if="!visible.length && query.trim()" class="empty">
      <Icon name="search" :size="28" />
      <p class="empty-title">No roles match “{{ query.trim() }}”.</p>
      <p><button type="button" class="link" @click="query = ''">Clear the search</button></p>
    </div>
    <div v-else-if="!visible.length" class="empty">
      <Icon name="inbox" :size="28" />
      <p class="empty-title">Everything here is hidden for this session.</p>
    </div>

    <div v-if="!error && visible.length" class="split" :class="{ 'show-detail': detailOpen, refreshing: loading }">
      <ul class="job-list surface" aria-label="New roles" @keydown="onListKey">
        <li
          v-for="job in visible"
          :key="job.id"
          class="card"
          :class="{ selected: selected && job.id === selected.id, closed: job.closed }"
          :data-job="job.id"
        >
          <button
            :ref="el => { itemEls[job.id] = el }"
            type="button"
            class="card-hit"
            :aria-current="selected && job.id === selected.id ? 'true' : undefined"
            @click="select(job)"
          >
            <CompanyMark :name="job.company" />
            <span class="card-body">
              <span class="title">{{ job.title }}</span>
              <span class="company">{{ job.company }}</span>
              <span class="meta">{{ cardMeta(job) }}</span>
            </span>
            <span class="card-side">
              <span v-if="job.closed" class="pill stale" data-status="closed">closed</span>
              <span class="seen">{{ shortDate(job.decided_at) }}</span>
            </span>
          </button>
        </li>
      </ul>

      <article v-if="selected" :key="selected.id" class="detail surface" aria-labelledby="detail-title" :data-job="selected.id">
        <button type="button" class="ghost back" @click="detailOpen = false">
          <Icon name="back" /> All roles
        </button>

        <header class="detail-head">
          <CompanyMark :name="selected.company" size="lg" />
          <div class="detail-names">
            <h3 id="detail-title" class="detail-title">{{ selected.title }}</h3>
            <p class="detail-company">{{ selected.company }}</p>
          </div>
        </header>

        <ul class="facts">
          <li v-if="selected.location"><Icon name="pin" /> {{ cleanLocation(selected.location) }}</li>
          <li v-if="years(selected)"><Icon name="briefcase" /> {{ years(selected) }}</li>
          <li v-if="selected.decided_at"><Icon name="clock" /> Found {{ shortDate(selected.decided_at) }}</li>
        </ul>

        <p v-if="selected.closed" class="notice warn stale-note">
          This posting has been taken down on the company's site.
        </p>

        <div class="actions">
          <a
            v-if="safeUrl(selected.url)"
            class="button primary open"
            :href="safeUrl(selected.url)"
            target="_blank"
            rel="noopener noreferrer"
            @click="markOpened(selected)"
          >Apply on company site <Icon name="external" /><span class="visually-hidden"> (opens {{ selected.company }} in a new tab)</span></a>
          <button type="button" class="apply" :disabled="busy" @click="track(selected, 'applied')">
            <Icon name="check" /> Mark applied
          </button>
          <button type="button" class="save" :disabled="busy" @click="track(selected, 'to_apply')">
            <Icon name="bookmark" /> Save
          </button>
          <button type="button" class="ghost dismiss" @click="notInterested(selected)">
            <Icon name="x" /> Not interested
          </button>
        </div>

        <div v-if="opened.has(selected.id)" class="did-apply" role="status">
          <span>Did you apply at {{ selected.company }}?</span>
          <button type="button" class="primary did-apply-yes" :disabled="busy" @click="track(selected, 'applied')">Yes, mark applied</button>
        </div>

        <section v-if="selected.reason" class="why">
          <h4><Icon name="target" /> Why it matches</h4>
          <p class="reason">{{ selected.reason }}</p>
        </section>

        <section v-if="selected.matched_skills && selected.matched_skills.length" class="why">
          <h4>Matched skills</h4>
          <ul class="skills" aria-label="Matched skills">
            <li v-for="skill in selected.matched_skills" :key="skill" class="chip">{{ skill }}</li>
          </ul>
        </section>
      </article>
    </div>
  </section>
</template>

<style scoped>
.page-controls .search { width: 17rem; max-width: 100%; }
.tracked { font-weight: 500; }

/* List and detail side by side; the detail stays in view while the list scrolls. */
.split {
  display: grid;
  grid-template-columns: minmax(18rem, 25rem) minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
  transition: opacity 0.15s;
}
.split.refreshing { opacity: 0.6; }

.job-list {
  list-style: none;
  margin: 0;
  padding: var(--space-1);
  max-height: calc(100vh - var(--header-h) - 9rem);
  overflow-y: auto;
  overscroll-behavior: contain;
}
.card + .card { border-top: 1px solid var(--border); }
.card-hit {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  width: 100%;
  min-height: 0;
  padding: var(--space-3);
  text-align: left;
  white-space: normal;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius);
  box-shadow: none;
  font-weight: 400;
}
.card-hit:hover:not(:disabled) { background: var(--surface-2); }
.card.selected .card-hit {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 35%, transparent);
}
.card-body { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.card .title { font-weight: 650; font-size: var(--text-sm); color: var(--text); line-height: 1.35; }
.card .company { font-size: var(--text-sm); color: var(--text-2); margin-top: 2px; }
.card .meta { font-size: var(--text-xs); color: var(--muted); margin-top: 2px; }
.card-side { display: flex; flex-direction: column; align-items: flex-end; gap: var(--space-1); flex: none; }
.seen { font-family: var(--mono); font-size: var(--text-xs); color: var(--muted); white-space: nowrap; }
.card.closed .card-body { opacity: 0.6; }

.detail {
  position: sticky;
  top: calc(var(--header-h) + var(--space-4));
  padding: var(--space-5);
}
.back { display: none; margin: calc(-1 * var(--space-2)) 0 var(--space-3) calc(-1 * var(--space-2)); }
.detail-head { display: flex; align-items: center; gap: var(--space-4); }
.detail-names { min-width: 0; }
.detail-title { margin: 0; font-size: var(--text-xl); font-weight: 650; letter-spacing: -0.01em; }
.detail-company { margin: var(--space-1) 0 0; color: var(--text-2); font-weight: 500; }

.facts {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-5);
  margin: var(--space-4) 0 0;
  padding: 0;
  color: var(--text-2);
  font-size: var(--text-sm);
}
.facts li { display: inline-flex; align-items: center; gap: var(--space-2); }
.facts .icon { color: var(--muted); }
.stale-note { margin: var(--space-4) 0 0; }

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-5);
  padding-bottom: var(--space-5);
  border-bottom: 1px solid var(--border);
}
.did-apply {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2) var(--space-3);
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--accent-soft);
  border-radius: var(--radius);
  font-size: var(--text-sm);
  font-weight: 500;
}

.why { margin-top: var(--space-5); }
.why h4 {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-2);
  font-size: var(--text-xs);
  font-weight: 650;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}
.reason { margin: 0; max-width: 68ch; color: var(--text); }
.skills { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: var(--space-1); }

.empty .icon { display: block; margin: 0 auto var(--space-2); }

/* A phone or a narrow window: one column. The list, or the role - not both. */
@media (max-width: 900px) {
  .split { grid-template-columns: minmax(0, 1fr); }
  .job-list { max-height: none; }
  .detail { position: static; display: none; }
  .split.show-detail .job-list { display: none; }
  .split.show-detail .detail { display: block; }
  .back { display: inline-flex; }
  .page-controls .search { width: 100%; }
  .page-controls { width: 100%; }
}
</style>
