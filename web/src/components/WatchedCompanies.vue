<script setup>
// The Companies table (Q-118 LD, design section 5): your list set against what JobScraper
// can read and has read, in one place.
//
//   559 in your list -> 433 watched -> 394 readable -> 120 checked this cycle
//   [bar]  (All) Checked this cycle . Due for a check . Failed . No job board found ...
//   one sortable table: Company . Job board . Open roles . Last checked . Status . Careers
//
// The legend under the bar IS the filter (it replaces the three number tiles, the view
// toggle and the "Watchlist and your list" select): the counts and the rows come from
// the same buckets, so they cannot disagree. Which bucket a company is in, and how
// "checked this cycle" is worked out, is in companyRows.js.
//
// Failed companies say why in words on a second line; the Failed view groups them by
// cause, each with what you can do. "Compact rows" (density.js) is remembered in this
// browser and follows the same switch in Settings -> Preferences.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { DENSITY_EVENT, densityCompact, setDensityCompact } from '../density.js'
import { ago, plural, safeUrl } from '../format.js'
import {
  BUCKETS, CAUSES, DEFAULT_SORT, bucketFromState, countsOf, funnelOf, matchesQuery, nextSort,
  partition, segmentsOf, sorted,
} from '../companyRows.js'
import ProgressSegments from '../ui/ProgressSegments.vue'
import SortHeader from '../ui/SortHeader.vue'
import CompanyMark from './CompanyMark.vue'
import Icon from './Icon.vue'

const props = defineProps({
  // GET /api/companies/health: every watched company.
  health: { type: Object, default: null },
  // GET /api/companies/list: your own list (null = none loaded).
  list: { type: Object, default: null },
  // The pipeline's cycle length in days; null = unknown (the settings did not load).
  cycleDays: { type: Number, default: null },
  error: { type: String, default: '' },
  // 'all' | 'ok' | 'failed' | 'not_scanned' or a bucket id - where the view starts.
  initialState: { type: String, default: 'all' },
})
const emit = defineEmits(['retry'])

const query = ref('')
const bucket = ref(bucketFromState(props.initialState))   // '' = all
const cause = ref('all')
const sort = ref({ ...DEFAULT_SORT })
const searchEl = ref(null)

// ---- density (G30): remembered in this browser (density.js) ----
// The button here and the Settings -> Preferences switch write the same key and tell
// each other through a window event, so whichever is open follows the other.
const compact = ref(densityCompact())
function toggleDensity() {
  setDensityCompact(!compact.value)
  compact.value = densityCompact()
}
function onDensity(e) {
  compact.value = typeof e.detail?.on === 'boolean' ? e.detail.on : densityCompact()
}
window.addEventListener(DENSITY_EVENT, onDensity)
onBeforeUnmount(() => window.removeEventListener(DENSITY_EVENT, onDensity))

watch(bucket, () => { cause.value = 'all' })

// ---- the buckets, the funnel and the legend ----
const cycleKnown = computed(() => Number(props.cycleDays) > 0)
const now = ref(Date.now())
watch(() => props.health, () => { now.value = Date.now() })
const buckets = computed(() => partition(props.health, props.list, props.cycleDays, now.value))
const counts = computed(() => countsOf(buckets.value))
const everything = computed(() => BUCKETS.flatMap(b => buckets.value[b]))
const funnel = computed(() => funnelOf(props.health, props.list, counts.value, cycleKnown.value))
const segments = computed(() => segmentsOf(counts.value, cycleKnown.value))

// A bucket that has no legend item (e.g. the first-load view asked for one that is empty
// and hidden) cannot stay chosen with nothing to un-choose it.
watch(segments, segs => {
  if (bucket.value && !segs.some(s => s.id === bucket.value)) bucket.value = ''
})

// ---- what the table shows ----
const inBucket = computed(() => (bucket.value ? buckets.value[bucket.value] ?? [] : everything.value))
const failedHere = computed(() => (buckets.value.failed ?? []).filter(r => matchesQuery(r, query.value)))
const causes = computed(() => {
  const n = {}
  for (const r of failedHere.value) n[r.kind] = (n[r.kind] ?? 0) + 1
  return Object.keys(CAUSES).filter(k => n[k]).map(k => ({ id: k, n: n[k], ...CAUSES[k] }))
})
const shown = computed(() => sorted(
  inBucket.value
    .filter(r => matchesQuery(r, query.value))
    .filter(r => bucket.value !== 'failed' || cause.value === 'all' || r.kind === cause.value),
  sort.value,
))
const filtering = computed(() => Boolean(query.value.trim() || bucket.value))

function onSort(column) { sort.value = nextSort(sort.value, column) }

function clearFilters() {
  query.value = ''
  bucket.value = ''
  cause.value = 'all'
  searchEl.value?.focus()
}

const lastChecked = r => (r.lastChecked ? ago(String(r.lastChecked).replace(' ', 'T')) : '')
const lastCheckedTitle = r => (r.lastChecked ? `${String(r.lastChecked).replace('T', ' ').slice(0, 16)} UTC` : '')
</script>

<template>
  <div class="watched">
    <div v-if="!health && !error" class="watched-loading" role="status" aria-busy="true">
      <span class="visually-hidden">Loading…</span>
      <span class="ui-skeleton line-skel" aria-hidden="true" />
      <span class="ui-skeleton bar-skel" aria-hidden="true" />
      <span v-for="n in 5" :key="n" class="ui-skeleton row-skel" aria-hidden="true" />
    </div>
    <div v-else-if="!health" class="notice error" role="alert">
      <p>Could not read the watched companies: {{ error }}</p>
      <button type="button" @click="emit('retry')">Try again</button>
    </div>

    <template v-else>
      <!-- Your list -> watched -> readable -> checked this cycle. -->
      <p class="funnel">
        <template v-if="funnel.list">
          <span class="funnel-step"><span class="num funnel-n">{{ funnel.list }}</span> in your list</span>
          <span class="funnel-arrow" aria-hidden="true">→</span>
        </template>
        <span class="funnel-step"><span class="num funnel-n">{{ funnel.watched }}</span> watched</span>
        <span class="funnel-arrow" aria-hidden="true">→</span>
        <span class="funnel-step"><span class="num funnel-n">{{ funnel.readable }}</span> readable</span>
        <template v-if="funnel.checked !== null">
          <span class="funnel-arrow" aria-hidden="true">→</span>
          <span class="funnel-step"><span class="num funnel-n">{{ funnel.checked }}</span> checked this cycle</span>
        </template>
      </p>

      <ProgressSegments v-model="bucket" mode="filter" label="Show companies" all-label="All" :segments="segments" />

      <div class="toolbar">
        <label class="search grow">
          <Icon name="search" />
          <span class="visually-hidden">Search companies</span>
          <input
            ref="searchEl"
            v-model="query"
            type="search"
            class="company-search"
            placeholder="Search by company, job board or reason…"
            autocomplete="off"
            aria-keyshortcuts="/"
            @keydown.esc="query = ''"
          >
          <kbd class="key-hint" aria-hidden="true">/</kbd>
        </label>
        <button
          type="button"
          class="density"
          :class="{ active: compact }"
          :aria-pressed="compact ? 'true' : 'false'"
          @click="toggleDensity"
        >Compact rows</button>
      </div>

      <!-- Failed: the causes, each with what to do, and a filter of its own. -->
      <section v-if="bucket === 'failed' && causes.length" class="causes" aria-label="Why they failed">
        <button
          type="button"
          class="chip is-filter cause"
          :aria-pressed="cause === 'all' ? 'true' : 'false'"
          @click="cause = 'all'"
        >
          <span class="cause-label">Every cause</span>
          <span class="num cause-n">{{ failedHere.length }}</span>
        </button>
        <button
          v-for="c in causes"
          :key="c.id"
          type="button"
          class="chip is-filter cause"
          :aria-pressed="cause === c.id ? 'true' : 'false'"
          :data-cause="c.id"
          @click="cause = c.id"
        >
          <span class="cause-label">{{ c.label }}</span>
          <span class="num cause-n">{{ c.n }}</span>
        </button>
      </section>
      <p v-if="bucket === 'failed' && cause !== 'all'" class="cause-fix" role="note">
        <strong>What you can do:</strong> {{ CAUSES[cause].fix }}
      </p>

      <p class="result-line muted" aria-live="polite">
        {{ plural(shown.length, 'company', 'companies') }}<template v-if="query.trim()"> matching “{{ query.trim() }}”</template>
        <template v-if="filtering">
          · <button type="button" class="ghost clear-filters" @click="clearFilters">Clear filters</button>
        </template>
      </p>

      <section v-if="shown.length" class="ui-card table-card">
        <table class="ui-table companies-table" :class="{ 'is-compact': compact }" data-stack>
          <caption class="visually-hidden">Companies</caption>
          <thead>
            <tr>
              <SortHeader label="Company" column="company" :sort="sort" @sort="onSort" />
              <th scope="col">Job board</th>
              <SortHeader label="Open roles" column="roles" :sort="sort" numeric @sort="onSort" />
              <SortHeader label="Last checked" column="checked" :sort="sort" @sort="onSort" />
              <th scope="col">Status</th>
              <th scope="col" class="col-action"><span class="visually-hidden">Careers page</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in shown" :key="r.key" :data-bucket="r.bucket">
              <td class="co-cell">
                <span class="co-line">
                  <CompanyMark :name="r.company" size="sm" />
                  <span class="co-name">{{ r.company }}</span>
                </span>
              </td>
              <td data-label="Job board" :class="{ 'is-empty': !r.board }">{{ r.board }}</td>
              <td class="col-num" data-label="Open roles" :class="{ 'is-empty': r.openRoles === null }">{{ r.openRoles }}</td>
              <td data-label="Last checked" :class="{ 'is-empty': !lastChecked(r) }" :title="lastCheckedTitle(r)">{{ lastChecked(r) }}</td>
              <td class="status-cell">
                <span class="ui-badge" :data-tone="r.tone" :title="r.title || undefined">{{ r.badge }}</span>
                <span v-if="r.reason" class="status-note">{{ r.reason }}</span>
              </td>
              <td class="col-action">
                <a
                  v-if="safeUrl(r.url)"
                  class="button ghost careers"
                  :href="r.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  :aria-label="`Careers page for ${r.company}`"
                  :title="`Careers page for ${r.company}`"
                ><Icon name="external" /></a>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
      <div v-else class="empty none">
        <Icon name="search" :size="24" />
        <p class="empty-title">No companies match.</p>
        <p class="muted">Try another spelling, or <button type="button" class="link" @click="clearFilters">clear the filters</button>.</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.watched-loading { display: grid; gap: var(--space-3); }
.line-skel { height: 1.5rem; width: min(100%, 34rem); }
.bar-skel { height: 0.6rem; border-radius: var(--radius-pill); }
.row-skel { height: var(--row-h); }

.funnel {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--space-1) var(--space-2);
  margin: 0 0 var(--space-3); font-size: var(--text-md); color: var(--text-2);
}
.funnel-n { font-weight: var(--weight-semibold); color: var(--text); }
.funnel-arrow { color: var(--muted); }
.funnel-step { white-space: nowrap; }

.toolbar { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; margin: var(--space-4) 0 var(--space-3); }
.grow { flex: 1 1 16rem; }
.density.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }

.causes { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-bottom: var(--space-2); }
.cause-n { color: var(--muted); }
.cause[aria-pressed='true'] .cause-n { color: inherit; }
.cause-fix {
  margin: 0 0 var(--space-3); padding: var(--space-3) var(--space-4); font-size: var(--text-sm);
  background: var(--surface-2); border-radius: var(--radius);
}

.result-line { margin: 0 0 var(--space-2); font-size: var(--text-sm); }
.result-line .clear-filters { min-height: 0; padding: 0 var(--space-2); }

/* The table fills the card edge to edge; it scrolls sideways rather than squeeze a column. */
.table-card { padding: 0; overflow-x: auto; }
.companies-table th:first-child, .companies-table td:first-child { padding-left: var(--space-4); }
.companies-table th:last-child, .companies-table td:last-child { padding-right: var(--space-4); }
.companies-table tbody tr:last-child td { border-bottom: 0; }
.co-line { display: inline-flex; align-items: center; gap: var(--space-2); min-width: 0; }
.co-name { font-weight: var(--weight-semibold); overflow-wrap: anywhere; }
.status-cell { min-width: 11rem; }
.status-note { display: block; margin-top: 2px; font-size: var(--text-xs); color: var(--muted); max-width: 26rem; }
.careers { min-height: 1.75rem; min-width: 1.75rem; padding: 0 var(--space-1); }
.is-compact .co-line :deep(.mark) { display: none; }
.is-compact .status-note { display: inline; margin-left: var(--space-2); }

.none { padding: var(--space-6) var(--space-4); }

@media (max-width: 640px) {
  .table-card { overflow-x: visible; }
  .companies-table td.co-cell { order: -2; padding-left: 0; }
  .companies-table td.col-action { order: -1; padding-right: 0; }
  .companies-table td.status-cell { order: 1; flex: 1 1 100%; min-width: 0; }
  .companies-table td.is-empty { display: none; }
  .careers { min-height: var(--touch-min); min-width: var(--touch-min); }
  .result-line .clear-filters { min-height: var(--touch-min); }
  .status-note { max-width: none; }
  .is-compact .status-note { display: block; margin-left: 0; }
}
</style>
