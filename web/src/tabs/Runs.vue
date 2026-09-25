<script setup>
// Placeholder until M12-T2: start a run, watch it, and the run history.
import { tabEmits, tabProps } from '../shell.js'

defineProps(tabProps)
defineEmits(tabEmits)
</script>

<template>
  <section class="runs empty">
    <p class="empty-title">Runs</p>
    <p class="muted">Starting and watching runs from here is coming next.</p>
  </section>
</template>
