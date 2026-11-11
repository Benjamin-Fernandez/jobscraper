<script setup>
// The shell's "something you connected needs you" line (Q-100 design §1, §4.4),
// under the masthead on every tab except Settings → Accounts (where the hub
// itself shows it). One item: "{Name} needs attention. {line} [Fix it]"; several:
// "{n} connections need attention. [Review]". Each leads into the hub at the card
// to fix (`#/settings/accounts/<item>`).
//
// The button says "See how to fix" where the fix is a command to run (Wave 1:
// the application mailbox and employer accounts) and "Fix it" where it is a
// button in the app (MailCard, Check again).
//
// Dismiss lasts for this browser session. What is remembered is the sorted
// `id:code` list, so a new problem - or the same item failing in a new way -
// brings the banner back.
//
// A polite live region (role="status", not alert): the region is always in the
// page, so a screen reader hears the line when it appears. The words say what is
// wrong; the amber edge and the mark only repeat it (WCAG 1.4.1).
import { computed, ref } from 'vue'
import { codeCopy } from '../connections.js'
import { hashFor } from '../route.js'

const props = defineProps({
  // The items that need attention (connections.js `attentionItems`).
  items: { type: Array, default: () => [] },
  // The shell hides the line where the hub is open.
  hidden: { type: Boolean, default: false },
})

const NAMES = {
  gmail: 'Email updates',
  apply_mailbox: 'Application mailbox',
  employer_accounts: 'Employer accounts',
  edge: 'Apply browser',
  model: 'Local AI',
}
// Wave 1: these are fixed with a CLI command shown on the card.
const BY_COMMAND = new Set(['apply_mailbox', 'employer_accounts'])

function readDismissed() {
  try { return window.sessionStorage.getItem(DISMISS_KEY) || '' } catch { return '' }
}
const dismissed = ref(readDismissed())

const signature = computed(() => props.items.map(i => `${i.id}:${i.code}`).sort().join('|'))
const shown = computed(() => !props.hidden && props.items.length > 0 && signature.value !== dismissed.value)
const one = computed(() => (props.items.length === 1 ? props.items[0] : null))

const title = computed(() => (one.value
  ? `${NAMES[one.value.kind] ?? 'A connection'} needs attention.`
  : `${props.items.length} connections need attention.`))
const line = computed(() => (one.value ? codeCopy(one.value) : null))
const href = computed(() => hashFor('settings', 'accounts', one.value ? one.value.id : null))
const action = computed(() => {
  if (!one.value) return 'Review'
  return BY_COMMAND.has(one.value.kind) ? 'See how to fix' : 'Fix it'
})

function dismiss() {
  dismissed.value = signature.value
  try { window.sessionStorage.setItem(DISMISS_KEY, signature.value) } catch { /* private window */ }
}
</script>

<script>
// The sessionStorage key behind Dismiss (a test may clear it).
export const DISMISS_KEY = 'attention.dismissed'
</script>

<template>
  <div class="attention-region" role="status">
    <div v-if="shown" class="attention-banner" data-attention-banner>
      <div class="attention-inner">
        <svg class="attention-mark" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
          <path d="M12 3.5 21.5 20h-19z" />
          <path d="M12 10v4.5M12 17.2v.3" />
        </svg>
        <p class="attention-text">
          <strong>{{ title }}</strong>
          <template v-if="line"> {{ line }}</template>
        </p>
        <div class="attention-actions">
          <a class="button attention-go" :href="href">{{ action }}</a>
          <button type="button" class="ghost attention-dismiss" @click="dismiss">Dismiss</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.attention-banner {
  background: var(--state-attention-bg);
  border-bottom: 1px solid color-mix(in srgb, var(--state-attention-fg) 35%, transparent);
  border-left: 4px solid var(--state-attention-fg);
}
.attention-inner {
  max-width: var(--page-w);
  margin: 0 auto;
  padding: var(--space-2) var(--gutter);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-3);
}
.attention-mark { flex: none; }
.attention-mark path { fill: none; stroke: var(--state-attention-fg); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.attention-text {
  flex: 1 1 20rem;
  min-width: 0;
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text);
  overflow-wrap: anywhere;
  text-wrap: pretty;
}
.attention-text strong { font-weight: 650; }
.attention-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
@media (max-width: 640px) {
  .attention-go, .attention-dismiss { min-height: var(--touch-min); }
}
</style>
