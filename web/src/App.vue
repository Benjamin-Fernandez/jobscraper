<script setup>
// The one page. M7-T2 adds the tab shell and the run selector here.
</script>

<template>
  <div class="shell">
    <header class="bar">
      <h1>JobScraper</h1>
    </header>
    <main>
      <p class="empty">Nothing to show yet.</p>
    </main>
  </div>
</template>

<style scoped>
.shell { max-width: 960px; margin: 0 auto; padding: 0 16px 48px; }
.bar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 16px 0; }
h1 { font-size: 1.25rem; margin: 0; }
.empty { color: var(--muted); }
</style>
