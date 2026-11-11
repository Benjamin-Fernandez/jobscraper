<script setup>
// Settings → Accounts: the Connected accounts hub (Q-100 design §4.1). One card per
// thing JobScraper signs in to or talks to - Gmail, the application mailbox, the apply
// browser, the local AI, the employer accounts - each with its state, a line saying why,
// and one action. The owner sees what works and what needs them in one place.
//
// The data is Settings.vue's (GET /api/connections, loaded there so the Accounts view
// tab can carry the attention count); this component draws it, polls it and answers
// deep links. Polling: every 30 s while the page is open, every 3 s (at most 5 times)
// after "Check again" or while an item is `checking`. A failed load shows "Couldn't
// load your connections" with Try again, never a blank and never a false "all good".
//
// Deep links `#/settings/accounts/<item>` scroll to the item's card and focus its
// heading. Nothing here shows, asks for or copies a password (D-191); employer emails
// are shown in full (D-193).
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { COPY, codeCopy } from '../connections.js'
import { checkModel } from '../connections_api.js'
import { when } from '../format.js'
import { useHashItem } from '../route.js'
import ConnectionCard from './ConnectionCard.vue'
import EmployerAccounts from './EmployerAccounts.vue'
import MailCard from './MailCard.vue'
import StateChip from './StateChip.vue'
import TabLoading from './TabLoading.vue'

const props = defineProps({
  // The GET /api/connections answer, or null before the first one / when it failed.
  connections: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  failed: { type: Boolean, default: false },
})
const emit = defineEmits(['reload'])

const SLOW_MS = 30000
const FAST_MS = 3000
const FAST_TRIES = 5

const items = computed(() => (Array.isArray(props.connections?.items) ? props.connections.items : []))
const byKind = kind => items.value.filter(i => i.kind === kind)
const one = kind => byKind(kind)[0] ?? null

// ---- Gmail: one card for every gmail:<id> item ----
const RANK = { attention: 0, neutral: 1, checking: 2, connected: 3, paused: 4, not_set_up: 5 }
const worst = list => [...list].sort((a, b) => (RANK[a.state] ?? 9) - (RANK[b.state] ?? 9))[0] ?? null

const gmail = computed(() => byKind('gmail'))
const gmailItem = computed(() => worst(gmail.value) ?? {
  kind: 'gmail', state: 'not_set_up', code: 'none', optional: true,
})
const gmailLine = computed(() => {
  const list = gmail.value
  if (list.length <= 1) return codeCopy(gmailItem.value) || ''
  const bad = list.filter(i => i.state === 'attention').length
  if (bad) return `${bad} of ${list.length} mailboxes need attention`
  const off = list.filter(i => i.state === 'paused').length
  return off ? `${list.length} mailboxes, ${off} switched off` : `${list.length} mailboxes connected`
})
const latest = (list, key) => list.map(i => i[key]).filter(Boolean).sort().at(-1) ?? null
const earliest = (list, key) => list.map(i => i[key]).filter(Boolean).sort()[0] ?? null
const gmailChecked = computed(() => latest(gmail.value, 'checked_at'))
const gmailNext = computed(() => earliest(gmail.value, 'next_check_at'))

// ---- the application mailbox (and its optional backup) ----
const mailbox = computed(() => items.value.find(i => i.id === 'apply-mailbox') ?? null)
const backup = computed(() => items.value.find(i => i.id === 'apply-mailbox:backup') ?? null)
const backupShown = computed(() => backup.value && backup.value.state !== 'not_set_up')

function mailFix(item, backupBox = false) {
  if (!item || !['attention', 'not_set_up'].includes(item.state)) return null
  const flag = backupBox ? ' --backup' : ''
  const setUp = item.state === 'not_set_up' && !item.facts?.username
  return {
    note: 'In PowerShell, in the JobScraper folder. It asks for the app password, so the password never goes through this page.',
    commands: [
      setUp
        ? `.\\run.ps1 mail set-password${flag} --host imap.gmail.com --user you@gmail.com`
        : `.\\run.ps1 mail set-password${flag}`,
      `.\\run.ps1 mail test${flag}`,
    ],
  }
}

// ---- the apply browser ----
const edge = computed(() => one('edge'))
const edgeUsed = computed(() => (edge.value?.facts?.last_used_at ? `Last used ${when(edge.value.facts.last_used_at)}.` : ''))

// ---- local AI ----
const model = computed(() => one('model'))
const modelChecking = ref(false)
const noCheckAgain = new Set(['ai_off', 'misconfigured', 'probing'])
const canCheck = computed(() => model.value && !noCheckAgain.has(model.value.code))

// ---- employer accounts ----
const employers = computed(() => one('employer_accounts'))
const employerRows = computed(() => (Array.isArray(props.connections?.employer_accounts) ? props.connections.employer_accounts : []))
const employerLine = computed(() => {
  const e = employers.value
  if (!e) return ''
  if (e.state === 'not_set_up') return ''
  const total = e.facts?.total ?? employerRows.value.length
  const bad = e.facts?.attention ?? 0
  const noun = total === 1 ? 'account' : 'accounts'
  return bad ? `${total} ${noun}, ${bad} need${bad === 1 ? 's' : ''} attention` : `${total} ${noun}`
})

// ---- deep links ----
const hashItem = useHashItem('settings')
// 'gmail:3' and 'apply-mailbox:backup' belong to the card of their first part.
const target = computed(() => (hashItem.value ? hashItem.value.split(':')[0] : null))
const root = ref(null)

async function goTo() {
  const want = target.value
  if (!want || !props.connections) return
  await nextTick()
  const card = root.value?.querySelector(`[data-card="${want}"]`)
  if (!card) return
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
  card.scrollIntoView?.({ block: 'start', behavior: reduce ? 'auto' : 'smooth' })
  card.querySelector('.conn-title')?.focus({ preventScroll: true })
}
watch([target, () => Boolean(props.connections)], goTo, { immediate: true, flush: 'post' })

// ---- Check again (the model) ----
let burst = 0
async function checkAgain() {
  if (modelChecking.value) return
  modelChecking.value = true
  try {
    await checkModel()      // null when the route is absent: just look again
  } catch {
    /* the next read shows the real state */
  } finally {
    modelChecking.value = false
  }
  burst = FAST_TRIES
  emit('reload')
  arm()
}

// ---- polling ----
let timer = null
let open = false
const anyChecking = computed(() => items.value.some(i => i.state === 'checking'))

function disarm() {
  clearTimeout(timer)
  timer = null
}
function arm() {
  disarm()
  if (!open || (typeof document !== 'undefined' && document.hidden)) return
  const fast = burst > 0 || anyChecking.value
  timer = setTimeout(() => {
    if (burst > 0) burst -= 1
    emit('reload')
    arm()
  }, fast ? FAST_MS : SLOW_MS)
}
function onVisible() {
  if (document.hidden) { disarm(); return }
  emit('reload')
  arm()
}
function start() {
  if (open) return
  open = true
  document.addEventListener('visibilitychange', onVisible)
  arm()
}
function stop() {
  open = false
  disarm()
  document.removeEventListener('visibilitychange', onVisible)
}
watch(anyChecking, arm)
onMounted(start)
onActivated(start)
onDeactivated(stop)
onBeforeUnmount(stop)
</script>

<template>
  <div ref="root" class="hub">
    <h3 class="section-title hub-title">Connected accounts</h3>
    <p class="hub-sub">
      Everything JobScraper signs in to. Passwords stay in Windows Credential Manager on this PC;
      the app never shows them.
    </p>

    <TabLoading v-if="loading && !connections" :rows="3" />

    <template v-else-if="!connections">
      <div class="notice error hub-error" role="alert">
        <p>{{ COPY.hubError }}</p>
        <button type="button" class="hub-retry" @click="emit('reload')">Try again</button>
      </div>
      <!-- Gmail keeps working without the hub: the mailbox card loads its own data. -->
      <h3 class="section-title">Email</h3>
      <MailCard />
    </template>

    <div v-else class="hub-cards">
      <p v-if="failed" class="muted hub-stale" role="status">Couldn't refresh just now. Showing the last result.</p>

      <ConnectionCard
        card-id="gmail"
        icon="✉"
        title="Application updates from email"
        :item="gmailItem"
        :line="gmailLine"
        :checked-at="gmailChecked"
        :next-check-at="gmailNext"
        :target="target === 'gmail'"
      >
        <MailCard embedded />
        <p class="hub-link"><a href="#/applications">See status changes from email in Applications</a></p>
      </ConnectionCard>

      <ConnectionCard
        v-if="mailbox"
        card-id="apply-mailbox"
        icon="⌂"
        title="Application mailbox"
        :item="mailbox"
        :line="codeCopy(mailbox) || ''"
        :fix="mailFix(mailbox)"
        :target="target === 'apply-mailbox'"
      >
        <p v-if="mailbox.facts?.username" class="hub-fact">
          Mailbox: <span class="hub-value">{{ mailbox.facts.username }}</span>
          <template v-if="mailbox.facts.host"> on {{ mailbox.facts.host }}</template>
        </p>
        <div v-if="backupShown" class="hub-backup" data-card-part="apply-mailbox:backup">
          <p class="hub-fact">
            Backup mailbox
            <span v-if="backup.facts?.username" class="hub-value">{{ backup.facts.username }}</span>
            <StateChip :item="backup" label="Backup mailbox" />
          </p>
          <p v-if="codeCopy(backup)" class="hub-fact muted">{{ codeCopy(backup) }}</p>
          <details v-if="mailFix(backup, true)" class="hub-backup-fix">
            <summary>See how to fix the backup mailbox</summary>
            <pre v-for="c in mailFix(backup, true).commands" :key="c" class="code-wrap">{{ c }}</pre>
          </details>
        </div>
      </ConnectionCard>

      <ConnectionCard
        v-if="edge"
        card-id="edge"
        icon="◫"
        title="Apply browser"
        :item="edge"
        :line="codeCopy(edge) || ''"
        :target="target === 'edge'"
      >
        <p v-if="edgeUsed" class="hub-fact muted">{{ edgeUsed }}</p>
      </ConnectionCard>

      <ConnectionCard
        v-if="model"
        card-id="model"
        icon="◎"
        title="Local AI"
        :item="model"
        :line="codeCopy(model) || ''"
        :checked-at="model.checked_at"
        :next-check-at="model.next_check_at"
        :target="target === 'model'"
      >
        <template #actions>
          <button v-if="canCheck" type="button" class="check-again" :disabled="modelChecking" @click="checkAgain">
            {{ modelChecking ? 'Checking…' : 'Check again' }}
          </button>
        </template>
      </ConnectionCard>

      <ConnectionCard
        v-if="employers"
        card-id="employer-accounts"
        icon="⚿"
        title="Employer accounts"
        :item="employers"
        :line="employerLine"
        :target="target === 'employer-accounts'"
      >
        <EmployerAccounts
          :accounts="employerRows"
          :no-account-needed="connections.no_account_needed || undefined"
        />
      </ConnectionCard>
    </div>
  </div>
</template>

<style scoped>
.hub { display: grid; gap: var(--space-3); }
.hub-title { margin: 0; }
.hub-sub { margin: 0; color: var(--text-2); font-size: var(--text-sm); max-width: 40rem; text-wrap: pretty; }
.hub-cards { display: grid; gap: var(--space-3); }
.hub-error { max-width: 34rem; margin: 0; }
.hub-stale, .hub-fact, .hub-link { margin: 0; font-size: var(--text-sm); }
.hub-fact { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-2); }
.hub-value { font-weight: 600; overflow-wrap: anywhere; }
.hub-backup { display: grid; gap: var(--space-1); padding-top: var(--space-2); border-top: 1px solid var(--border); }
.hub-backup-fix summary, .hub-link a { display: inline-flex; align-items: center; min-height: 2rem; }
.hub-backup-fix summary { cursor: pointer; font-size: var(--text-sm); font-weight: 600; color: var(--accent); }
@media (max-width: 640px) {
  .hub-backup-fix summary, .hub-link a { min-height: var(--touch-min); }
}
</style>
