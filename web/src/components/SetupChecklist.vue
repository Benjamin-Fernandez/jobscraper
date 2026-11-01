<script setup>
// Getting started (UX-1): shown by the empty Inbox instead of a dead end. It
// reads what already exists - resume, job titles, companies, runs - ticks those
// steps and points at the next one. Once every step is done, it shows its slot
// (the Inbox's usual empty state) instead. A request that fails counts its step
// as not done, and a note says some steps could not be checked.
import { computed, onMounted, ref } from 'vue'
import { getCompanyHealth, getCompanyList, getProfile, getTitles } from '../api.js'
import { setupSteps } from '../setup.js'
import Icon from './Icon.vue'

const props = defineProps({
  runs: { type: Array, default: () => [] },
})

const facts = ref(null)
const unknown = ref(false)          // a request failed: its step may be done after all

const quietly = promise => promise.catch(() => {
  unknown.value = true
  return null
})

onMounted(async () => {
  const [profile, titles, list, health] = await Promise.all([
    quietly(getProfile()), quietly(getTitles()), quietly(getCompanyList()), quietly(getCompanyHealth()),
  ])
  facts.value = {
    hasResume: Boolean(profile?.present),
    titleCount: titles?.titles?.length ?? 0,
    // Your own list, or companies already watched (the curated watchlist).
    companyCount: Math.max(list?.items?.length ?? 0, health?.total ?? 0),
  }
})

const steps = computed(() => (facts.value ? setupSteps({ ...facts.value, runCount: props.runs.length }) : []))
const done = computed(() => steps.value.filter(s => s.done).length)
const nextId = computed(() => steps.value.find(s => !s.done)?.id ?? null)
</script>

<template>
  <template v-if="facts">
    <section v-if="nextId" class="setup surface" aria-labelledby="setup-title">
      <header class="setup-head">
        <div>
          <h3 id="setup-title" class="setup-title">Get your first matches</h3>
          <p class="setup-sub muted">Four steps, once. After that, new roles arrive here after every run.</p>
        </div>
        <p class="setup-progress num">{{ done }} of {{ steps.length }} done</p>
      </header>
      <p v-if="unknown" class="notice warn setup-unknown" role="status">
        Could not check every step just now, so some may already be done. Open a step to see.
      </p>
      <div class="setup-bar" aria-hidden="true">
        <span :style="{ width: `${(done / steps.length) * 100}%` }" />
      </div>
      <ol class="setup-steps">
        <li
          v-for="(step, i) in steps"
          :key="step.id"
          class="setup-step"
          :class="{ done: step.done, next: step.id === nextId }"
          :data-step="step.id"
        >
          <span class="setup-mark" aria-hidden="true">
            <Icon v-if="step.done" name="check" :size="14" />
            <template v-else>{{ i + 1 }}</template>
          </span>
          <span class="setup-text">
            <span class="setup-label">
              {{ step.label }}<span v-if="step.done" class="visually-hidden"> (done)</span>
            </span>
            <span class="setup-hint muted">{{ step.hint }}</span>
          </span>
          <a
            class="button setup-go"
            :class="{ primary: step.id === nextId, ghost: step.done }"
            :href="step.href"
          >{{ step.done ? 'Review' : step.cta }}</a>
        </li>
      </ol>
    </section>
    <slot v-else />
  </template>
</template>

<style scoped>
.setup { padding: var(--space-5); }
.setup-head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: var(--space-2) var(--space-4); }
.setup-title { margin: 0; font-size: var(--text-lg); font-weight: 650; text-wrap: balance; }
.setup-sub { margin: var(--space-1) 0 0; font-size: var(--text-sm); text-wrap: pretty; }
.setup-progress { margin: 0; font-size: var(--text-sm); color: var(--text-2); }
.setup-unknown { margin: var(--space-3) 0 0; }
.setup-bar { height: 4px; margin: var(--space-3) 0 var(--space-2); border-radius: 999px; background: var(--surface-3); overflow: hidden; }
.setup-bar span { display: block; height: 100%; background: var(--ok); border-radius: inherit; transition: width 0.3s ease-out; }
.setup-steps { list-style: none; margin: 0; padding: 0; }
.setup-step {
  display: grid; grid-template-columns: 1.75rem minmax(0, 1fr) auto; align-items: center;
  gap: var(--space-3); padding: var(--space-3) 0; border-top: 1px solid var(--border);
}
.setup-step:first-child { border-top: 0; }
.setup-mark {
  display: inline-flex; align-items: center; justify-content: center;
  width: 1.75rem; height: 1.75rem; border-radius: 50%;
  font-family: var(--mono); font-size: var(--text-xs); font-weight: 600;
  color: var(--muted); border: 1px solid var(--border-strong); background: var(--surface);
}
.setup-step.next .setup-mark { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
.setup-step.done .setup-mark { color: var(--ok); border-color: transparent; background: var(--ok-soft); }
.setup-text { display: grid; min-width: 0; }
.setup-label { font-weight: 600; font-size: var(--text-sm); }
.setup-step.done .setup-label { color: var(--text-2); font-weight: 500; }
.setup-hint { font-size: var(--text-sm); text-wrap: pretty; }
@media (max-width: 640px) {
  .setup-step { grid-template-columns: 1.75rem minmax(0, 1fr); }
  .setup-go { grid-column: 2; justify-self: start; }
}
</style>
