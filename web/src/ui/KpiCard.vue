<script setup>
// One headline number with a label and a caption (Q-118 design section 1, 2): the
// Overview's KPI row ("New roles 101 - in your Inbox").
//
//   <KpiCard label="New roles" :value="101" caption="in your Inbox" href="#/inbox" />
//   <KpiCard label="Response rate" :value="null" caption="No applications sent yet." />
//
// An `a.ui-kpi` when `href` is given (the whole card is the link, named
// "{label}: {value}, {caption}"), else a `div.ui-kpi`. `value` may be a number, a string
// ("72%") or null: null leaves the caption alone (nothing to measure yet). `hint` is the
// longer explanation: it is the tooltip and also visually hidden text that a link's
// accessible description points at.
import { computed, useId } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: null },
  caption: { type: String, default: '' },
  hint: { type: String, default: '' },
  href: { type: String, default: '' },
})

const uid = useId()
const hintId = computed(() => `ui-kpi-${uid}-hint`)
const hasValue = computed(() => props.value !== null && props.value !== undefined && props.value !== '')
const linkName = computed(() => {
  const head = hasValue.value ? `${props.label}: ${props.value}` : props.label
  return props.caption ? `${head}, ${props.caption}` : head
})
</script>

<template>
  <component
    :is="href ? 'a' : 'div'"
    class="ui-kpi"
    :class="{ 'is-link': href, 'is-empty': !hasValue }"
    :href="href || undefined"
    :aria-label="href ? linkName : undefined"
    :aria-describedby="href && hint ? hintId : undefined"
    :title="hint || undefined"
  >
    <span class="ui-kpi-label">{{ label }}</span>
    <span v-if="hasValue" class="ui-kpi-value num">{{ value }}</span>
    <span v-if="caption" class="ui-kpi-caption">{{ caption }}</span>
    <span v-if="hint" :id="hintId" class="visually-hidden">{{ hint }}</span>
  </component>
</template>

<style scoped>
.ui-kpi {
  position: relative; /* contains the visually hidden hint */
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: var(--space-4);
  color: var(--text);
  text-decoration: none;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}
a.ui-kpi { transition: border-color var(--motion) var(--ease-out), box-shadow var(--motion) var(--ease-out); }
a.ui-kpi:hover { color: var(--text); border-color: var(--border-strong); box-shadow: var(--shadow); }
a.ui-kpi:focus-visible { border-radius: var(--radius-lg); }

.ui-kpi-label { font-size: var(--text-sm); font-weight: var(--weight-medium); color: var(--text-2); }
.ui-kpi-value {
  font-size: var(--text-3xl);
  font-weight: var(--weight-semibold);
  line-height: var(--leading-tight);
  overflow-wrap: anywhere;
}
.ui-kpi-caption { font-size: var(--text-xs); color: var(--muted); }
/* Nothing to measure yet: the caption is the content. */
.ui-kpi.is-empty .ui-kpi-caption { font-size: var(--text-sm); }

@media (max-width: 640px) {
  .ui-kpi { padding: var(--space-3); }
}
@media (prefers-reduced-motion: reduce) {
  a.ui-kpi { transition: none; }
}
</style>
