<script setup>
// Settings -> Apply -> "Answers you corrected" (Q-127 U3, D-215; q127_profile_questions_design
// B.2b, B.4 copy table). The answers the owner saved from an application ("Use a different
// answer next time" in What was sent), newest first: the title over "{answer} · {scope}", and
// Forget. It sits in Settings, not Profile, because it grows only by the owner's own clicks and
// keeps the Profile free of question wording (R1). The first 20 show, then "Show all {n}".
//
// Data: GET /api/apply/remembered -> {items: [{key, title, value_text, scope_text, employer,
// kind, sensitive, needs_attention}], count, etag, unreadable}. Forget is DELETE with that
// etag: a stale etag answers 409, and the list is then read again and the owner is told, so a
// Forget never lands on a list the owner has not seen. The component loads itself when it is
// shown and tells its row the count (`count`: a number, or null when it could not be read);
// `missing` means the server has no such route (an older server), so the row can be hidden.
// Nothing here starts an application or changes the profile except the one DELETE.
//
// Keyboard: the Forget confirm opens with focus on "Keep" (the safe choice); Esc or Keep puts
// focus back on that item's Forget button; after a Forget it goes to the next item's button,
// else the one before, else the empty message.
import { computed, nextTick, onMounted, ref } from 'vue'
import { ApiError, forgetRemembered, getRemembered, problemOf } from '../api.js'

const emit = defineEmits(['count', 'missing'])

// The copy table's words (design B.4).
const SHOWN_FIRST = 20
const EMPTY_TEXT = 'None yet. To save one, open an application and choose What was sent.'
const CONFIRM_TEXT = 'Forget this answer? JobScraper will answer this question from your details again.'
const CHANGED_TEXT = 'The saved answers changed since this list was loaded. The list is up to date now. Choose Forget again if you still want to.'
const GONE_TEXT = 'That answer was already gone. The list is up to date now.'

const root = ref(null)
const data = ref(null)            // the last good GET, or null
const loading = ref(true)
const loadError = ref('')
const showAll = ref(false)
const confirmKey = ref('')        // the item whose Forget confirm is open
const busyKey = ref('')           // the item whose DELETE is in flight
const note = ref('')              // a line above the list: what a refused Forget meant
const noteTone = ref('warn')

const items = computed(() => (Array.isArray(data.value?.items) ? data.value.items : []))
const unreadable = computed(() => data.value?.unreadable === true)
const shown = computed(() => (showAll.value ? items.value : items.value.slice(0, SHOWN_FIRST)))
const hiddenCount = computed(() => Math.max(0, items.value.length - shown.value.length))

// "Every application" or "Only {employer}", from the server's words when it sent them.
function scopeOf(item) {
  const text = String(item?.scope_text ?? '').trim()
  if (text) return text
  const employer = String(item?.employer ?? '').trim()
  return employer ? `Only ${employer}` : 'Every application'
}
// The route sends `title` = the saved wording, or the raw key when an answer was saved before
// this feature existed (then `title` equals the key, e.g. "location_city"). A raw key is never
// shown: the first of `labels` if the route sends any, else the key as words ("Location city").
function titleOf(item) {
  const key = String(item?.key ?? '')
  const title = String(item?.title ?? '').trim()
  if (title && title !== key) return title
  const labels = Array.isArray(item?.labels) ? item.labels : []
  const label = labels.map(l => String(l ?? '').trim()).find(Boolean)
  if (label) return label
  const words = (title || key).replace(/_+/g, ' ').trim()
  return words ? words[0].toUpperCase() + words.slice(1) : 'Saved answer'
}
function detailOf(item) {
  const answer = String(item?.value_text ?? '').trim()
  return answer ? `${answer} · ${scopeOf(item)}` : scopeOf(item)
}

function tell(count) {
  emit('count', Number.isFinite(count) ? count : null)
}

async function load({ keepNote = false } = {}) {
  loading.value = true
  loadError.value = ''
  if (!keepNote) note.value = ''
  try {
    const next = await getRemembered()
    if (!next || !Array.isArray(next.items)) throw new Error('The server sent no list.')
    data.value = next
    tell(next.unreadable ? null : Number(next.count ?? next.items.length))
  } catch (e) {
    data.value = null
    loadError.value = e instanceof ApiError && e.status === 404
      ? 'This server does not offer saved answers yet. Update JobScraper and restart the web app.'
      : problemOf(e).text
    if (e instanceof ApiError && e.status === 404) emit('missing')
    tell(null)
  } finally {
    loading.value = false
  }
}
onMounted(() => load())

function forgetButton(key) {
  return [...(root.value?.querySelectorAll('.rem-forget') ?? [])].find(b => b.dataset.key === key) ?? null
}

async function ask(key) {
  confirmKey.value = key
  await nextTick()
  root.value?.querySelector('.rem-keep')?.focus()
}
async function keep(key) {
  confirmKey.value = ''
  await nextTick()
  forgetButton(key)?.focus()
}

async function forget(item) {
  if (busyKey.value) return
  const key = item.key
  busyKey.value = key
  note.value = ''
  // Where focus goes once this item is gone: the next one, else the one before.
  const at = shown.value.findIndex(i => i.key === key)
  const neighbour = shown.value[at + 1] ?? shown.value[at - 1] ?? null
  try {
    const reply = await forgetRemembered(key, data.value?.etag)
    const left = items.value.filter(i => i.key !== key)
    data.value = { ...data.value, items: left, count: left.length, etag: reply?.etag ?? data.value?.etag }
    confirmKey.value = ''
    tell(left.length)
    noteTone.value = 'ok'
    note.value = 'Forgotten.'
    await nextTick()
    if (neighbour) forgetButton(neighbour.key)?.focus()
    else root.value?.querySelector('.rem-empty, .rem-note')?.focus()
  } catch (e) {
    const p = problemOf(e)
    confirmKey.value = ''
    if (p.status === 409 || p.status === 404) {
      // A stale list: read it again, then say so (the owner decides again on what is there).
      await load({ keepNote: true })
      noteTone.value = 'warn'
      note.value = p.status === 404 ? GONE_TEXT : CHANGED_TEXT
    } else {
      noteTone.value = 'error'
      note.value = `Couldn't forget it. ${p.text}`
    }
    await nextTick()
    forgetButton(key)?.focus()
  } finally {
    busyKey.value = ''
  }
}

defineExpose({ reload: load })
</script>

<template>
  <div ref="root" class="remembered" :aria-busy="loading ? 'true' : undefined">
    <div v-if="loading && !data" class="rem-loading" role="status">
      <span class="visually-hidden">Loading your saved answers…</span>
      <span class="ui-skeleton rem-sk" aria-hidden="true" />
      <span class="ui-skeleton rem-sk" aria-hidden="true" />
    </div>

    <div v-else-if="loadError" class="notice error rem-notice" role="alert">
      <p>Couldn't load your saved answers. {{ loadError }}</p>
      <button type="button" class="rem-retry" @click="load()">Try again</button>
    </div>

    <p v-else-if="unreadable" class="notice warn rem-notice rem-unreadable" role="status">
      Your details file can't be read, so your saved answers can't be listed.
      <a class="text-link" href="#/profile/details">Open Your details</a> to see why.
    </p>

    <template v-else>
      <p
        v-if="note"
        class="rem-note"
        :class="`tone-${noteTone}`"
        :role="noteTone === 'error' ? 'alert' : 'status'"
        tabindex="-1"
      >{{ note }}</p>

      <p v-if="!items.length" class="rem-empty muted" tabindex="-1">{{ EMPTY_TEXT }}</p>

      <ul v-else class="rem-list">
        <li v-for="item in shown" :key="item.key" class="rem-item" :data-key="item.key">
          <div class="rem-line">
            <div class="rem-text">
              <span class="rem-title">{{ titleOf(item) }}</span>
              <span class="rem-detail">{{ detailOf(item) }}</span>
              <span
                v-if="item.needs_attention"
                class="ui-badge rem-attention"
                data-tone="warn"
                title="This saved answer no longer passes its checks, so forms ignore it."
              >Needs attention</span>
            </div>
            <button
              type="button"
              class="rem-forget"
              :data-key="item.key"
              :aria-label="`Forget ${titleOf(item)}`"
              :aria-expanded="confirmKey === item.key ? 'true' : 'false'"
              :disabled="busyKey === item.key"
              @click="ask(item.key)"
            >Forget</button>
          </div>
          <div
            v-if="confirmKey === item.key"
            class="rem-confirm"
            role="group"
            :aria-label="`Forget ${titleOf(item)}?`"
            @keydown.esc.stop.prevent="keep(item.key)"
          >
            <p class="rem-confirm-text">{{ CONFIRM_TEXT }}</p>
            <div class="rem-confirm-buttons">
              <button
                type="button"
                class="primary rem-confirm-yes"
                :disabled="busyKey === item.key"
                @click="forget(item)"
              >{{ busyKey === item.key ? 'Forgetting…' : 'Forget' }}</button>
              <button type="button" class="rem-keep" @click="keep(item.key)">Keep</button>
            </div>
          </div>
        </li>
      </ul>

      <p v-if="hiddenCount > 0" class="rem-more-line">
        <button type="button" class="rem-more" @click="showAll = true">Show all {{ items.length }}</button>
      </p>
    </template>
  </div>
</template>

<style scoped>
.remembered { display: grid; gap: var(--space-3); }
.rem-loading { display: grid; gap: var(--space-2); }
.rem-sk { display: block; min-height: 3rem; border-radius: var(--radius); }
.rem-notice { margin: 0; }
.rem-note { margin: 0; padding: var(--space-2) var(--space-3); font-size: var(--text-sm); border-radius: var(--radius); background: var(--surface-2); }
.rem-note.tone-warn { background: var(--warn-soft); }
.rem-note.tone-error { color: var(--danger); }
.rem-empty { margin: 0; font-size: var(--text-sm); }

.rem-list { list-style: none; margin: 0; padding: 0; display: grid; }
.rem-item { padding: var(--space-3) 0; }
.rem-item + .rem-item { border-top: 1px solid var(--border); }
.rem-line { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.rem-text { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; min-width: 0; }
.rem-title { font-size: var(--text-sm); font-weight: 600; overflow-wrap: anywhere; }
.rem-detail { font-size: var(--text-sm); color: var(--text-2); overflow-wrap: anywhere; }
.rem-attention { margin-top: var(--space-1); }
.rem-forget { flex: none; min-height: 2.25rem; }
.rem-confirm {
  display: grid; gap: var(--space-2); margin-top: var(--space-2); padding: var(--space-3);
  background: var(--warn-soft); border-radius: var(--radius);
}
.rem-confirm-text { margin: 0; font-size: var(--text-sm); }
.rem-confirm-buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.rem-more-line { margin: 0; }

@media (max-width: 640px) {
  .rem-forget, .rem-more, .rem-retry, .rem-confirm-buttons button { min-height: var(--touch-min); }
  .rem-line { align-items: flex-start; }
}
</style>
