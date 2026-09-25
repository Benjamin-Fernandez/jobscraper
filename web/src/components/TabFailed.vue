<script setup>
// Shown when a tab's code chunk cannot be loaded - most often because the app
// was rebuilt while this page was open, so the old chunk names are gone.
function reload() {
  window.location.reload()
}
</script>

<template>
  <div class="notice error" role="alert">
    <p>This tab could not be loaded. The app may have been updated since this page was opened.</p>
    <button type="button" @click="reload">Reload the page</button>
  </div>
</template>
