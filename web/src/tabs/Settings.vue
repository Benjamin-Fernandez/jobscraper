<script setup>
// Settings: one page, four categories (Q-116 design; it grows Q-100's four views).
//
//   Accounts      the Connected accounts hub (ConnectionsHub), unchanged
//   Apply         how applying works, limits, writing, what to fill in (ApplySettings)
//   Search        the cycle and companies per run, pointers to titles and companies
//   Preferences   theme, compact company list, keyboard shortcuts (this browser only)
//
// This file is the shell: the header, the category rail (SettingsRail), the phone
// screens, the routes and the two reads the panels share. The rows live in the panels.
//
// Routes (`#/settings/<category>[/<row-id>]`, design section 4). The category is read by
// `useView`, the row id by `useHashItem` here; a panel gets the id as its `item` prop only
// while its category is open, and is mounted only then, so only that panel acts on it. The hub is mounted the
// same way (`v-if`, never `v-show`): it reads the hash item without checking the
// category, so a mounted hub would act on another category's row id.
//   - `#/settings`          Accounts on a desktop (hash left alone); on a phone the list.
//   - `#/settings/appearance[/...]` was the old name of Preferences: it is rewritten with
//     `replaceState` before `useView` reads it, and again on each `hashchange` by a
//     listener registered before `useView`'s.
//   - an unknown category becomes `#/settings/accounts` (`useView` writes it).
//
// Phone (<= 640px): with no category in the hash the page is the category list; a
// category is its own screen with a "Settings" back link. The list's links are plain
// anchors, so choosing one pushes a history entry and the phone's Back returns to the
// list. Focus follows (design section 6): a drill-in focuses the category title, Back
// focuses the entry just left.
//
// Data: ONE GET /api/connections (the hub, the Accounts badge and the mailbox row of
// Apply) and ONE loadApplyData() (status, settings, details), loaded when the page
// opens and again when it is re-activated. A missing or failed answer is never "all
// good": no badge, and the hub or the Apply rows say so.
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { loadApplyData, missingLabels } from '../applyData.js'
import { attentionCount } from '../connections.js'
import { getApplyStatus, getConnections } from '../connections_api.js'
import { parseHash, useHashItem, useView } from '../route.js'
import { COPY } from '../settingsRows.js'
import { tabEmits, tabProps } from '../shell.js'
import ApplySettings from '../components/ApplySettings.vue'
import ConnectionsHub from '../components/ConnectionsHub.vue'
import Icon from '../components/Icon.vue'
import PreferencesSettings from '../components/PreferencesSettings.vue'
import SearchSettings from '../components/SearchSettings.vue'
import SettingsRail from '../components/SettingsRail.vue'
import TabLoading from '../components/TabLoading.vue'

defineProps(tabProps)
defineEmits(tabEmits)

// ---- the old name of Preferences ----
// Registered BEFORE useView's own listener, so a `hashchange` is rewritten first.
function aliasAppearance() {
  const h = window.location.hash
  if (!/^#\/settings\/appearance(?:\/|$)/.test(h)) return
  window.history.replaceState(window.history.state, '', h.replace('#/settings/appearance', '#/settings/preferences'))
}
aliasAppearance()
window.addEventListener('hashchange', aliasAppearance)

// ---- categories ----
const CATEGORIES = [
  { id: 'accounts', label: COPY.categories.accounts, icon: 'key' },
  { id: 'apply', label: COPY.categories.apply, icon: 'send' },
  { id: 'search', label: COPY.categories.search, icon: 'search' },
  { id: 'preferences', label: COPY.categories.preferences, icon: 'sliders' },
]
const view = useView('settings', CATEGORIES, 'accounts')
// The row id of `#/settings/<category>/<row-id>`; each panel gets it only while its own
// category is open (the hub reads the same hash item itself).
const item = useHashItem('settings')

// ---- connections (the hub's data) ----
const connections = ref(null)
const connLoading = ref(true)
const connFailed = ref(false)
let previous = null            // the last good answer: a single blip is not yet a problem
const attention = ref(0)

async function loadConnections() {
  try {
    const next = await getConnections()
    if (next === null) throw new Error('absent')
    attention.value = attentionCount(next, previous)
    previous = next
    connections.value = next
    connFailed.value = false
  } catch {
    // Keep the last good answer on screen, but count nothing from a failed load.
    attention.value = 0
    connFailed.value = true
  } finally {
    connLoading.value = false
  }
}

// ---- Apply's data: { status, settings, summary }, each null when unavailable ----
const apply = ref(null)        // null until the first answer
let applySeq = 0
async function loadApply() {
  const seq = ++applySeq
  const data = await loadApplyData()
  if (seq === applySeq) apply.value = data
}

// A save in the Apply panel: take the saved settings as they are, and re-read the
// status (mode, busy) because the mode chip and "an application is running" depend on it.
async function onApplySaved(next) {
  if (apply.value && next) apply.value = { ...apply.value, settings: next }
  // Tells the shell (App.vue) to re-read the apply status for its mode chip.
  window.dispatchEvent(new Event('jobscraper:apply-settings'))
  try {
    const status = await getApplyStatus()
    if (status && apply.value) apply.value = { ...apply.value, status }
  } catch { /* keep the status we had */ }
}

const missingCount = computed(() => missingLabels(apply.value?.summary).length)

const categories = computed(() => CATEGORIES.map(c => ({
  ...c,
  badge: c.id === 'accounts' ? attention.value : c.id === 'apply' ? missingCount.value : 0,
  badgeText: c.id === 'accounts' ? 'need attention' : 'details to fill in',
})))
const current = computed(() => categories.value.find(c => c.id === view.value) ?? categories.value[0])

function reload() {
  loadConnections()
  loadApply()
}
let shownOnce = false
onMounted(() => {
  shownOnce = true
  reload()
})
onActivated(() => {
  if (shownOnce) {
    shownOnce = false     // the mount already loaded
    return
  }
  reload()
})

// ---- phone ----
const mq = typeof window.matchMedia === 'function' ? window.matchMedia('(max-width: 640px)') : null
const phone = ref(Boolean(mq?.matches))
const onMedia = e => { phone.value = e.matches }
if (mq?.addEventListener) mq.addEventListener('change', onMedia)
else mq?.addListener?.(onMedia)

// Is a category named in the hash? (`useView` leaves `#/settings` alone, so the view
// alone can't tell the phone whether to show the list.) A replaceState fires no
// `hashchange`, so a rail click bumps the tick itself.
const hashTick = ref(0)
const bump = () => { hashTick.value += 1 }
window.addEventListener('hashchange', bump)
const hashParts = computed(() => {
  void hashTick.value
  return parseHash(window.location.hash, ['settings'])
})
const showList = computed(() => phone.value && hashParts.value.view === null)

function selectView(id) {
  view.value = id
  bump()
}

const titleEl = ref(null)
let lastView = null
watch(showList, async list => {
  if (!phone.value) return
  if (!list) lastView = view.value
  await nextTick()
  if (list) {
    document.getElementById(`settings-list-${lastView ?? view.value}`)?.focus()
    return
  }
  if (hashParts.value.item) return        // the hub scrolls to and focuses its card
  const title = view.value === 'accounts'
    ? document.querySelector('#settings-panel-accounts .hub-title')
    : titleEl.value
  if (title) {
    title.setAttribute('tabindex', '-1')
    title.focus()
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('hashchange', aliasAppearance)
  window.removeEventListener('hashchange', bump)
  if (mq?.removeEventListener) mq.removeEventListener('change', onMedia)
  else mq?.removeListener?.(onMedia)
})
</script>

<template>
  <section class="settings">
    <header class="page-head">
      <div>
        <h2 class="page-title">{{ COPY.title }}</h2>
        <p v-if="!phone || showList" class="page-sub">{{ COPY.subtitle }}</p>
      </div>
    </header>

    <!-- Phone, no category yet: the list. -->
    <nav v-if="showList" class="cat-list" :aria-label="COPY.railLabel">
      <ul>
        <li v-for="c in categories" :key="c.id">
          <a :id="`settings-list-${c.id}`" class="cat-link" :href="`#/settings/${c.id}`">
            <Icon :name="c.icon" :size="18" />
            <span class="cat-name">{{ c.label }}</span>
            <span v-if="c.badge > 0" class="view-badge">
              <span aria-hidden="true">{{ c.badge }}</span>
              <span class="visually-hidden">{{ c.badge }} {{ c.badgeText }}</span>
            </span>
            <Icon class="cat-chevron" name="chevron" :size="16" />
          </a>
        </li>
      </ul>
    </nav>

    <div v-else class="settings-grid">
      <SettingsRail v-if="!phone" :categories="categories" :model-value="view" @update:model-value="selectView" />

      <div class="settings-main">
        <a v-if="phone" class="back-link" href="#/settings" :aria-label="COPY.backLabel">
          <span aria-hidden="true">‹</span> {{ COPY.title }}
        </a>

        <div
          :id="`settings-panel-${view}`"
          :role="phone ? undefined : 'tabpanel'"
          :aria-labelledby="phone ? undefined : `settings-tab-${view}`"
        >
          <h3 v-if="view !== 'accounts'" ref="titleEl" class="section-title cat-title" tabindex="-1">{{ current.label }}</h3>

          <ConnectionsHub
            v-if="view === 'accounts'"
            :connections="connections"
            :loading="connLoading"
            :failed="connFailed"
            @reload="loadConnections"
          />
          <template v-else-if="view === 'apply'">
            <ApplySettings
              v-if="apply"
              :connections="connections"
              :apply="apply"
              :item="view === 'apply' ? item : null"
              @saved="onApplySaved"
            />
            <TabLoading v-else :rows="3" />
          </template>
          <SearchSettings v-else-if="view === 'search'" :item="view === 'search' ? item : null" />
          <PreferencesSettings v-else :item="view === 'preferences' ? item : null" />
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.settings-grid {
  display: grid; grid-template-columns: 15rem minmax(0, 44rem); gap: var(--space-6); align-items: start;
}
.settings-main { min-width: 0; }
.cat-title { margin-top: 0; }
.cat-title:focus-visible { outline-offset: 4px; }
/* The attention count: a dot and a number, so it is not colour alone. */
.view-badge {
  display: inline-flex; align-items: center; gap: var(--space-1);
  font-size: var(--text-xs); font-weight: 700; color: var(--state-attention-fg);
}
.view-badge::before { content: ''; width: 0.5rem; height: 0.5rem; border-radius: 50%; background: currentColor; }

/* The phone's category list. */
.cat-list ul { list-style: none; margin: 0; padding: 0; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); overflow: hidden; }
.cat-list li + li { border-top: 1px solid var(--border); }
.cat-link {
  display: flex; align-items: center; gap: var(--space-3); min-height: 3rem; box-sizing: border-box;
  padding: var(--space-3) var(--space-4); color: var(--text); text-decoration: none; font-weight: 600;
}
.cat-link:hover { background: var(--surface-2); color: var(--text); }
.cat-link:focus-visible { outline-offset: -2px; }
.cat-name { flex: 1 1 auto; min-width: 0; }
.cat-chevron { color: var(--muted); transform: rotate(-90deg); }
.back-link {
  display: inline-flex; align-items: center; gap: var(--space-1); min-height: var(--touch-min);
  margin-bottom: var(--space-2); font-weight: 600; text-decoration: none;
}

@media (max-width: 900px) {
  .settings-grid { grid-template-columns: 12rem minmax(0, 1fr); gap: var(--space-5); }
}
@media (max-width: 640px) {
  .settings-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
