<script setup>
// The accepted queue for the selected run. M7-T3 fills in the actions.
defineProps({
  run: { type: [Number, String], default: null },
  jobs: { type: Array, required: true },
})
</script>

<template>
  <section class="inbox">
    <p v-if="!jobs.length" class="empty">No roles in this run.</p>
    <ul v-else>
      <li v-for="job in jobs" :key="job.id">{{ job.company }} · {{ job.title }}</li>
    </ul>
  </section>
</template>
