<script setup>
// Placeholder until M12-T3: resume upload and the derived profile.
import { tabEmits, tabProps } from '../shell.js'

defineProps(tabProps)
defineEmits(tabEmits)
</script>

<template>
  <section class="profile empty">
    <p class="empty-title">Profile</p>
    <p class="muted">Uploading a resume from here is coming next.</p>
  </section>
</template>
