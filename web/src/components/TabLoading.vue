<script setup>
// Shown while a tab's code chunk loads (only if that takes over 150 ms), and
// by tabs themselves while their data loads. Placeholder rows hold roughly the
// space the content will take, so the page does not jump when it arrives.
defineProps({ rows: { type: Number, default: 3 } })
</script>

<template>
  <div class="skeleton" role="status" aria-busy="true">
    <span class="visually-hidden">Loading…</span>
    <div v-for="n in rows" :key="n" class="skeleton-row" aria-hidden="true">
      <span class="line wide" />
      <span class="line" />
    </div>
  </div>
</template>

<style scoped>
.skeleton-row { padding: 0.9rem 0; border-bottom: 1px solid var(--border); }
.line {
  display: block; height: 0.8rem; width: 40%; margin: 0.35rem 0;
  border-radius: 4px; background: var(--border);
  animation: pulse 1.4s ease-in-out infinite;
}
.line.wide { width: 70%; height: 1rem; }
@keyframes pulse { 50% { opacity: 0.45; } }
@media (prefers-reduced-motion: reduce) { .line { animation: none; } }
</style>
