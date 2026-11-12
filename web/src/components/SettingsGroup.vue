<script setup>
// A titled group of setting rows (Q-116 design §3): an `h4` over a surface card. The
// rows are SettingRow components in the default slot; each draws its own 1px top border
// against the row before it, so the group owns only the frame and every Settings
// category looks the same.
//
//   <SettingsGroup title="Limits">
//     <SettingRow id="daily-cap" label="..." ... />
//   </SettingsGroup>
defineProps({
  title: { type: String, required: true },
})
</script>

<template>
  <section class="settings-group">
    <h4 class="settings-group-title">{{ title }}</h4>
    <div class="settings-group-card">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.settings-group + .settings-group { margin-top: var(--space-5); }
.settings-group-title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-sm);
  font-weight: 650;
  color: var(--text-2);
}
.settings-group-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
</style>
