<script setup>
// One connection's state as a small chip (Q-100 design §2.1): "Connected", "Needs
// attention", "Not running", "Optional", "Paused", "Checking…". The words carry the
// meaning and a dot repeats the tone as a shape, so colour is never the only cue
// (style.css `.state-chip`). Used by the hub's cards, the employer rows, the Apply
// settings and the setup checklist.
//
//   <StateChip :item="item" />                        text from the item's state and code
//   <StateChip state="attention" text="Failed" />     explicit
//   <StateChip :item="item" label="Local AI" action @click="..." />   a button
//   <StateChip :item="item" href="#/settings/accounts/model" />       a link
//
// Not clickable by default. A button or link keeps the small look but gets a
// 44px hit area (`--touch-min`).
import { computed } from 'vue'
import { chipText, chipTone } from '../connections.js'

const props = defineProps({
  // An entry of `items` or `employer_accounts` (state, code, kind, optional).
  item: { type: Object, default: null },
  // Or the parts, when there is no item.
  state: { type: String, default: '' },
  code: { type: String, default: '' },
  kind: { type: String, default: '' },
  optional: { type: Boolean, default: false },
  // Replaces the default words.
  text: { type: String, default: '' },
  // What the chip is about ("Local AI"), for the accessible name.
  label: { type: String, default: '' },
  // Draw as a link / a button.
  href: { type: String, default: '' },
  action: { type: Boolean, default: false },
})
defineEmits(['click'])

const source = computed(() => ({
  state: props.state || props.item?.state || '',
  code: props.code || props.item?.code || '',
  kind: props.kind || props.item?.kind || '',
  optional: props.optional || Boolean(props.item?.optional),
}))
const tone = computed(() => chipTone(source.value.state))
const words = computed(() => props.text || chipText(source.value))
const name = computed(() => (props.label ? `${props.label}: ${words.value}` : words.value))
const tag = computed(() => (props.href ? 'a' : props.action ? 'button' : 'span'))
</script>

<template>
  <component
    :is="tag"
    class="state-chip"
    :class="{ 'is-action': tag !== 'span' }"
    :data-tone="tone"
    :href="href || undefined"
    :type="tag === 'button' ? 'button' : undefined"
    :role="tag === 'span' ? 'img' : undefined"
    :aria-label="name"
    @click="$emit('click', $event)"
  >{{ words }}</component>
</template>
