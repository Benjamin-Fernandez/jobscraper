<script setup>
// A share-of-the-whole bar with a legend that carries every number (Q-118 design
// section 1, 8): the Overview pipeline (links to a stage) and the Companies funnel
// (a filter).
//
//   <ProgressSegments label="Pipeline" :segments="[{ id: 'applied', label: 'Applied', n: 31, tone: 'applied', href: '#/applications/applied' }, ...]" />
//   <ProgressSegments mode="filter" v-model="bucket" label="Show companies" all-label="All" :segments="..." />
//
// segments: [{ id, label, n, tone, href?, note?, apart? }]
//   tone   a stage name (to_apply, applied, assessment, interviewing, offer, rejected,
//          withdrawn, closed) or a status tone (ok, info, warn, danger, neutral); unknown = neutral.
//   href   link mode: the legend item is an `a` named "{label}, {n}{ note}" (no href: plain text).
//   note   extra words after the count, e.g. "(1 withdrawn)"; part of the accessible name.
//   apart  leaves a wider gap before this segment (a closed bucket set apart from the open ones).
// mode 'link' (default): legend items are links. mode 'filter': legend items are
// `button[aria-pressed]` (one pressed at a time; pressing it again, or the optional
// leading "All" item, emits ''), and the bar dims the segments not chosen.
// The bar is decoration (`aria-hidden`): the legend says everything. A segment with n = 0
// has no bar slice (a visible slice is at least 6px wide) but stays in the legend, muted.
import { computed } from 'vue'

const props = defineProps({
  segments: { type: Array, required: true },
  mode: { type: String, default: 'link', validator: v => ['link', 'filter'].includes(v) },
  // Filter mode: the chosen segment id, '' for all.
  modelValue: { type: String, default: '' },
  // The legend's accessible name.
  label: { type: String, required: true },
  // Filter mode: text of the leading "show everything" item; empty = no such item.
  allLabel: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const total = computed(() => props.segments.reduce((sum, s) => sum + (Number(s.n) || 0), 0))
const slices = computed(() => props.segments.filter(s => Number(s.n) > 0))
const chosen = computed(() => (props.mode === 'filter' ? props.modelValue || '' : ''))

function nameOf(s) {
  return `${s.label}, ${s.n}${s.note ? ` ${s.note}` : ''}`
}
function pick(s) {
  emit('update:modelValue', chosen.value === s.id ? '' : s.id)
}
</script>

<template>
  <div class="ui-progress-wrap">
    <div class="ui-progress" :class="{ 'has-choice': Boolean(chosen) }" aria-hidden="true">
      <span
        v-for="s in slices"
        :key="s.id"
        class="ui-progress-seg"
        :class="{ 'is-apart': s.apart, 'is-dim': chosen && chosen !== s.id }"
        :data-tone="s.tone || 'neutral'"
        :style="{ flexGrow: Number(s.n) }"
      />
    </div>
    <ul class="ui-progress-legend" :aria-label="label">
      <li v-if="mode === 'filter' && allLabel">
        <button type="button" class="ui-progress-item" :aria-pressed="String(!chosen)" @click="emit('update:modelValue', '')">
          <span class="ui-progress-label">{{ allLabel }}</span>
          <span class="ui-progress-n num">{{ total }}</span>
        </button>
      </li>
      <li v-for="s in segments" :key="s.id" :class="{ 'is-zero': !Number(s.n) }">
        <a v-if="mode === 'link' && s.href" class="ui-progress-item" :href="s.href" :aria-label="nameOf(s)">
          <span class="ui-progress-swatch" :data-tone="s.tone || 'neutral'" aria-hidden="true" />
          <span class="ui-progress-label">{{ s.label }}</span>
          <span class="ui-progress-n num">{{ s.n }}</span>
          <span v-if="s.note" class="ui-progress-note">{{ s.note }}</span>
          <span class="ui-progress-go" aria-hidden="true">&rsaquo;</span>
        </a>
        <span v-else-if="mode === 'link'" class="ui-progress-item is-plain">
          <span class="ui-progress-swatch" :data-tone="s.tone || 'neutral'" aria-hidden="true" />
          <span class="ui-progress-label">{{ s.label }}</span>
          <span class="ui-progress-n num">{{ s.n }}</span>
          <span v-if="s.note" class="ui-progress-note">{{ s.note }}</span>
        </span>
        <button v-else type="button" class="ui-progress-item" :aria-pressed="String(chosen === s.id)" @click="pick(s)">
          <span class="ui-progress-swatch" :data-tone="s.tone || 'neutral'" aria-hidden="true" />
          <span class="ui-progress-label">{{ s.label }}</span>
          <span class="ui-progress-n num">{{ s.n }}</span>
          <span v-if="s.note" class="ui-progress-note">{{ s.note }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.ui-progress-wrap { display: flex; flex-direction: column; gap: var(--space-3); min-width: 0; }

.ui-progress { display: flex; gap: 2px; height: 0.75rem; min-width: 0; background: var(--surface-2); border-radius: var(--radius-pill); }
.ui-progress-seg {
  flex-basis: 0;
  min-width: 6px;
  border-radius: 3px;
  transition: opacity var(--motion) var(--ease-out);
}
.ui-progress-seg:first-child { border-top-left-radius: var(--radius-pill); border-bottom-left-radius: var(--radius-pill); }
.ui-progress-seg:last-child { border-top-right-radius: var(--radius-pill); border-bottom-right-radius: var(--radius-pill); }
.ui-progress-seg.is-apart { margin-left: var(--space-2); }
.ui-progress-seg.is-dim { opacity: 0.3; }

/* One colour per tone, from the stage and status tokens (3:1 against --surface in both themes). */
.ui-progress-seg, .ui-progress-swatch { background: var(--stage-closed); }
[data-tone='to_apply'] { background: var(--stage-saved); }
[data-tone='applied'], [data-tone='info'] { background: var(--stage-applied); }
[data-tone='assessment'] { background: var(--stage-assessment); }
[data-tone='interviewing'], [data-tone='warn'] { background: var(--stage-interview); }
[data-tone='offer'], [data-tone='ok'] { background: var(--stage-offer); }
[data-tone='rejected'], [data-tone='danger'] { background: var(--stage-rejected); }
[data-tone='withdrawn'], [data-tone='closed'], [data-tone='neutral'] { background: var(--stage-closed); }

.ui-progress-legend { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: var(--space-1) var(--space-3); }
.ui-progress-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 2rem;
  padding: 0 var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text);
  text-decoration: none;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius);
  box-shadow: none;
}
a.ui-progress-item:hover, button.ui-progress-item:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
button.ui-progress-item[aria-pressed='true'] { background: var(--accent-soft); border-color: var(--accent); color: var(--text); font-weight: var(--weight-semibold); }
.is-plain { cursor: default; }
.ui-progress-swatch { flex: none; width: 0.625rem; height: 0.625rem; border-radius: 3px; }
.ui-progress-n { font-weight: var(--weight-semibold); }
.ui-progress-note, .ui-progress-go { color: var(--muted); font-weight: 400; }
.is-zero .ui-progress-item { color: var(--muted); }
.is-zero .ui-progress-swatch { opacity: 0.5; }

@media (max-width: 640px) {
  .ui-progress-item { min-height: var(--touch-min); }
}
@media (prefers-reduced-motion: reduce) {
  .ui-progress-seg { transition: none; }
}
</style>
