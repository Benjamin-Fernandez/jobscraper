<script setup>
// The "From email" badge on a History event that an email made (Q-60, F-50l,
// F-50m; mail_status_design.md sections 8 and 11). Expanding it shows the line
// the email said, who sent it and when, a link to it in Gmail, and Undo while
// the change is still the application's latest event (`undoable`).
//
// The event carries `mail: {evidence_id, kind, state, quote, subject,
// sender_domain, received_at, gmail_url, undoable}` (MS section 11.1).
// Emits `undone` ({status}) after a successful Undo, and `stale` after a 409 on
// Undo, so the tab reloads either way.
import { computed, ref } from 'vue'
import { describeError, mailProblem, undoMailChange } from '../api.js'
import { shortDate } from '../format.js'
import { statusLabel } from '../stages.js'
import { showToast } from '../toast.js'

const props = defineProps({
  event: { type: Object, required: true },
})
const emit = defineEmits(['undone', 'stale'])

const UNDO_CONFLICT = "Can't undo: the status changed after this email. Set it by hand."

const open = ref(false)
const undoing = ref(false)
const error = ref('')

const mail = computed(() => props.event.mail ?? {})
const bodyId = computed(() => `mail-evidence-${props.event.id ?? mail.value.evidence_id}`)
const from = computed(() => [mail.value.sender_domain, shortDate(mail.value.received_at)].filter(Boolean))
// The link the server builds to the owner's own Gmail; never one taken from mail.
const gmail = computed(() => (/^https:\/\/mail\.google\.com\//.test(mail.value.gmail_url || '') ? mail.value.gmail_url : null))

async function undo() {
  if (undoing.value) return
  undoing.value = true
  error.value = ''
  try {
    const r = await undoMailChange(mail.value.evidence_id)
    if (r?.status) showToast({ message: `Back to ${statusLabel(r.status)}.` })
    emit('undone', { status: r?.status ?? null })
  } catch (e) {
    const p = mailProblem(e)
    error.value = p.status === 409 ? UNDO_CONFLICT : `Could not undo it: ${p.detail || describeError(e)}`
    // The status moved on (review F8): the tab reloads, so the History and its
    // Undo button show what is true now. This badge keeps its message: the
    // timeline is keyed by event id, so it survives the reload.
    if (p.status === 409) emit('stale')
  } finally {
    undoing.value = false
  }
}
</script>

<template>
  <span class="mail-evidence" :data-evidence="mail.evidence_id">
    <button
      type="button"
      class="mail-badge"
      :title="from.join(', ')"
      :aria-expanded="open ? 'true' : 'false'"
      :aria-controls="bodyId"
      @click="open = !open"
    >
      From email
    </button>
    <span v-if="open" :id="bodyId" class="evidence-body">
      <span v-if="mail.quote" class="evidence-quote">“{{ mail.quote }}”</span>
      <span class="evidence-from">{{ from.join(' · ') }}</span>
      <span class="evidence-actions">
        <a
          v-if="gmail"
          class="button ghost evidence-gmail"
          :href="gmail"
          target="_blank"
          rel="noopener noreferrer"
        >Open in Gmail</a>
        <button v-if="mail.undoable" type="button" class="evidence-undo" :disabled="undoing" @click="undo">Undo</button>
      </span>
      <span v-if="error" class="notice error evidence-error" role="alert">{{ error }}</span>
    </span>
  </span>
</template>

<style scoped>
/* Its parts sit in the timeline row; the expanded body takes a line of its own. */
.mail-evidence { display: contents; }
.mail-badge {
  min-height: 0; padding: 0 var(--space-2); border-radius: 999px;
  font-size: var(--text-xs); font-weight: 600; line-height: 1.7;
  color: var(--accent); background: var(--accent-soft);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent); box-shadow: none;
}
.mail-badge:hover:not(:disabled) { background: var(--accent-soft); color: var(--accent-hover); }
.evidence-body {
  flex: 1 0 100%; display: grid; gap: var(--space-1); margin: var(--space-1) 0 var(--space-2);
  padding: var(--space-2) var(--space-3); background: var(--surface-2); border-radius: var(--radius);
}
.evidence-quote { color: var(--text); font-size: var(--text-sm); overflow-wrap: anywhere; }
.evidence-from { color: var(--muted); font-size: var(--text-xs); }
.evidence-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.evidence-actions:empty { display: none; }
.evidence-error { display: block; margin: 0; }
</style>
