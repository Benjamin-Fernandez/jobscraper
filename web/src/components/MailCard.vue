<script setup>
// Application updates from email (Q-60, F-50a-c, F-50o; mail_status_design.md
// sections 4 and 11): the Settings card that connects Gmail mailboxes, read-only,
// and says how each one's checks went.
//
// The application mailbox (apply.mail, D-72) is offered first, with no password
// to type (F-50b). Another Gmail needs an app password. Both need the consent box
// ticked: its text comes from the server (contracts.CONSENT_TEXT), and so does its
// version, which goes back with the request.
//
// The app password never lives in component state. Its field has no v-model:
// the value is read from the element once, at submit, and the field is cleared
// right then, before the request goes out, so it is empty after every attempt,
// whatever the answer (MS section 13).
//
// While a check runs, GET /api/mail is polled every POLL_MS; otherwise the card
// refreshes when the window gets focus. Only a check this page has *seen*
// running raises "Check finished" when it ends: a 202 alone doesn't, or a read
// made before the child flags itself would announce a check that hasn't run.
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ApiError, connectApplicationMailbox, connectMailbox, describeError, disconnectMailbox, getMail,
  mailProblem, setMailboxEnabled, setMailboxPassword, startMailSync,
} from '../api.js'
import { ago, shortDate } from '../format.js'
import { showToast } from '../toast.js'
import TabLoading from './TabLoading.vue'

const POLL_MS = 5000
const APP_PASSWORDS_URL = 'https://myaccount.google.com/apppasswords'
// The server's own answer to an incomplete form (MS section 4, `bad_input`).
const BAD_INPUT = 'Enter your Gmail address and app password, and tick the box.'
// SYNC_TEXTS[DISABLED]: the account rows can't say it, so the card does.
const DISABLED_TEXT = 'Email updates are turned off in config.yaml (mail_status.enabled).'

const mail = ref(null)
const loading = ref(true)
const loadError = ref('')
const notOffered = ref(false)      // a server older than this page: no /api/mail

const consented = ref(false)
const address = ref('')
const pwInput = ref(null)          // the connect form's password <input>
const connecting = ref('')         // 'app' | 'other' while a login is tested
const appError = ref('')
const connectError = ref('')

const busy = ref({})               // account id -> 'switch' | 'password' | 'disconnect'
const rowError = ref({})           // account id -> text
const pwFor = ref(null)            // account id whose "Change app password" form is open
const pwFilled = ref(false)        // that form's field has text (never the text itself)
const confirming = ref(null)       // account id whose Disconnect dialog is open
const starting = ref(false)        // POST /api/mail/sync in flight
const checkError = ref('')

const root = ref(null)

const accounts = computed(() => mail.value?.accounts ?? [])
const running = computed(() => Boolean(mail.value?.sync?.running))
const consent = computed(() => mail.value?.consent ?? { version: '', text: '' })
const offerApp = computed(() => {
  const box = mail.value?.application_mailbox
  return Boolean(box && box.ready && !box.connected)
})

const patch = (target, key, v) => { target.value = { ...target.value, [key]: v } }

// ---- loading and polling ----

let timer = null
let alive = true
let inflight = null
let sawRunning = false
// Reads left that keep polling though no check is seen running: a check was just
// started (202, a connect), so the read after it may come before the child flags itself.
let lookAgain = 0

function schedule() {
  clearTimeout(timer)
  timer = null
  if (alive && (running.value || lookAgain > 0)) timer = setTimeout(load, POLL_MS)
}

function started() {
  lookAgain = 2
  return reload()
}

function countsSum(key) {
  return accounts.value.reduce((n, a) => n + (a.enabled ? Number(a.counts?.[key] ?? 0) : 0), 0)
}

async function fetchMail() {
  try {
    const next = await getMail()
    if (!alive) return
    loadError.value = ''
    notOffered.value = false
    mail.value = next
    if (next?.sync?.running) {
      sawRunning = true
      lookAgain = 0
    } else if (lookAgain > 0) {
      lookAgain -= 1
    }
    if (!next?.sync?.running && sawRunning) {
      sawRunning = false
      if (next?.sync?.last?.state !== 'failed') {
        showToast({ message: `Check finished: ${countsSum('applied')} updated, ${countsSum('suggested')} to review.` })
      }
    }
  } catch (e) {
    if (!alive) return
    if (e instanceof ApiError && e.status === 404) notOffered.value = true
    // A failed poll keeps what is shown and tries again on the next tick.
    else if (!mail.value) loadError.value = describeError(e)
  } finally {
    loading.value = false
  }
  schedule()
}

function load() {
  if (!inflight) inflight = fetchMail().finally(() => { inflight = null })
  return inflight
}

// After an action: a fresh read, not one that started before it.
async function reload() {
  if (inflight) await inflight
  return load()
}

function onFocus() {
  if (!running.value) load()
}

// ---- the row's words (MS section 11.3) ----

function statusLine(a) {
  if (!a.enabled) return "Off. JobScraper isn't reading this mailbox."
  if (running.value) return 'Checking…'
  if (a.state && a.state !== 'ok') return a.message || ''
  if (!a.last_sync_at) return `Not checked yet. The first check reads mail from ${shortDate(a.first_sync_from)}.`
  const c = a.counts ?? {}
  return `Checked ${ago(a.last_sync_at)}. ${c.applied ?? 0} updated, ${c.suggested ?? 0} to review.`
}

// A finished check that still has something to say (PARTIAL: "Still catching up").
function extraLine(a) {
  if (!a.enabled || running.value || (a.state && a.state !== 'ok')) return ''
  return a.code && a.code !== 'ok' ? a.message || '' : ''
}

function countLines(a) {
  if (!a.enabled || !a.last_sync_at) return []
  const c = a.counts ?? {}
  const out = []
  const pending = Number(c.pending_model ?? 0)
  const unmatched = Number(c.unmatched ?? 0)
  if (pending > 0) {
    out.push(pending === 1 ? '1 email is waiting for the AI model.' : `${pending} emails are waiting for the AI model.`)
  }
  if (unmatched > 0) {
    out.push(unmatched === 1
      ? '1 job email matched no tracked application.'
      : `${unmatched} job emails matched no tracked application.`)
  }
  return out
}

function disconnectBody(a) {
  return a.shared_with_apply
    ? 'JobScraper stops reading this mailbox and deletes its place in the mailbox and its list of '
      + 'checked emails. The app password stays, because email verification for auto-apply uses it. '
      + "Status changes already made stay in each application's history."
    : 'JobScraper stops reading this mailbox and deletes its app password from Windows Credential '
      + 'Manager, its place in the mailbox and its list of checked emails. Status changes already '
      + "made stay in each application's history."
}

// ---- connecting ----

function connected() {
  consented.value = false
  showToast({ message: 'Connected. The first check has started.' })
  return started()
}

async function useApp() {
  if (!consented.value || connecting.value) return
  appError.value = ''
  connecting.value = 'app'
  try {
    await connectApplicationMailbox(consent.value.version)
    await connected()
  } catch (e) {
    const p = mailProblem(e)
    appError.value = p.detail || `Could not connect: ${describeError(e)}`
  } finally {
    connecting.value = ''
  }
}

async function connect() {
  const el = pwInput.value
  const password = el ? el.value : ''
  if (el) el.value = ''
  connectError.value = ''
  if (!consented.value || connecting.value) return
  const addr = address.value.trim()
  if (!addr || !password) {
    connectError.value = BAD_INPUT
    return
  }
  connecting.value = 'other'
  try {
    await connectMailbox({ address: addr, appPassword: password, consentVersion: consent.value.version })
    address.value = ''
    await connected()
  } catch (e) {
    const p = mailProblem(e)
    connectError.value = p.detail || `Could not connect: ${describeError(e)}`
  } finally {
    connecting.value = ''
  }
}

// ---- one mailbox ----

function rowInput(id, selector) {
  return root.value?.querySelector(`.mail-account[data-account="${id}"] ${selector}`) ?? null
}

async function toggle(a, event) {
  const want = event.target.checked
  patch(busy, a.id, 'switch')
  patch(rowError, a.id, '')
  try {
    const view = await setMailboxEnabled(a.id, want)
    if (view && view.id === a.id && mail.value) {
      mail.value = { ...mail.value, accounts: accounts.value.map(x => (x.id === a.id ? view : x)) }
    } else {
      await reload()
    }
  } catch (e) {
    event.target.checked = a.enabled
    const p = mailProblem(e)
    patch(rowError, a.id, p.detail || `Could not change it: ${describeError(e)}`)
  } finally {
    patch(busy, a.id, '')
  }
}

async function checkNow() {
  if (starting.value || running.value) return
  starting.value = true
  checkError.value = ''
  try {
    await startMailSync()
    await started()
  } catch (e) {
    const p = mailProblem(e)
    if (p.status === 409) checkError.value = p.detail || 'A check is already running.'
    else if (p.code === 'no_mailbox') checkError.value = p.detail || 'Switch a mailbox on first, then check again.'
    else checkError.value = p.detail || `Could not start the check: ${describeError(e)}`
    await reload()
  } finally {
    starting.value = false
  }
}

async function openPassword(a) {
  confirming.value = null
  pwFor.value = a.id
  pwFilled.value = false
  patch(rowError, a.id, '')
  await nextTick()
  rowInput(a.id, '.password-form input')?.focus()
}

function closePassword() {
  const el = pwFor.value === null ? null : rowInput(pwFor.value, '.password-form input')
  if (el) el.value = ''
  pwFor.value = null
  pwFilled.value = false
}

async function savePassword(a) {
  const el = rowInput(a.id, '.password-form input')
  const password = el ? el.value : ''
  if (el) el.value = ''
  pwFilled.value = false
  if (!password || busy.value[a.id]) return
  patch(busy, a.id, 'password')
  patch(rowError, a.id, '')
  try {
    await setMailboxPassword(a.id, password)
    pwFor.value = null
    await started()
  } catch (e) {
    const p = mailProblem(e)
    patch(rowError, a.id, p.detail || `Could not change the app password: ${describeError(e)}`)
  } finally {
    patch(busy, a.id, '')
  }
}

async function askDisconnect(a) {
  closePassword()
  confirming.value = a.id
  await nextTick()
  rowInput(a.id, '.disconnect-no')?.focus()
}

async function keepConnected(a) {
  confirming.value = null
  await nextTick()
  rowInput(a.id, '.disconnect')?.focus()
}

async function disconnect(a) {
  if (busy.value[a.id]) return
  patch(busy, a.id, 'disconnect')
  patch(rowError, a.id, '')
  try {
    await disconnectMailbox(a.id)
    confirming.value = null
    await reload()
  } catch (e) {
    const p = mailProblem(e)
    patch(rowError, a.id, p.detail || `Could not disconnect it: ${describeError(e)}`)
  } finally {
    patch(busy, a.id, '')
  }
}

onMounted(() => {
  load()
  window.addEventListener('focus', onFocus)
})

onBeforeUnmount(() => {
  alive = false
  clearTimeout(timer)
  window.removeEventListener('focus', onFocus)
})

defineExpose({ load })
</script>

<template>
  <div ref="root" class="mail-card surface" :aria-busy="loading ? 'true' : 'false'">
    <h3 class="mail-title">Application updates from email</h3>
    <p class="mail-intro">
      Connect Gmail and JobScraper updates your applications when employers write: received,
      assessment, interview, offer or rejection. Each change shows the email line it came from,
      and you can undo it.
    </p>

    <TabLoading v-if="loading" :rows="1" />
    <p v-else-if="notOffered" class="muted not-offered">
      This server doesn't offer email updates yet. Update JobScraper and restart the web app.
    </p>
    <div v-else-if="loadError" class="notice error" role="alert">
      <p>Could not load the email settings: {{ loadError }}</p>
      <button type="button" @click="load">Try again</button>
    </div>

    <template v-else-if="mail">
      <p v-if="mail.enabled === false" class="notice warn mail-disabled">{{ DISABLED_TEXT }}</p>

      <ul v-if="accounts.length" class="mail-accounts">
        <li
          v-for="a in accounts"
          :key="a.id"
          class="mail-account"
          :data-account="a.id"
          :data-state="a.state"
          :data-enabled="a.enabled ? 'true' : 'false'"
        >
          <div class="account-head">
            <span class="account-address">{{ a.address }}</span>
            <label class="switch">
              <input
                type="checkbox"
                role="switch"
                class="switch-input"
                :checked="a.enabled"
                :disabled="Boolean(busy[a.id])"
                :aria-describedby="`mail-status-${a.id}`"
                @change="toggle(a, $event)"
              >
              <span class="switch-track" aria-hidden="true"><span class="switch-thumb" /></span>
              <span class="switch-label">Read this mailbox</span>
            </label>
          </div>

          <p :id="`mail-status-${a.id}`" class="account-status" :class="{ failed: a.enabled && !running && a.state && a.state !== 'ok' }">
            {{ statusLine(a) }}
          </p>
          <p v-if="extraLine(a)" class="account-message">{{ extraLine(a) }}</p>
          <ul v-if="a.enabled && a.notes && a.notes.length" class="account-notes">
            <li v-for="n in a.notes" :key="n.code" class="account-note" :data-code="n.code">{{ n.message }}</li>
          </ul>
          <p v-for="line in countLines(a)" :key="line" class="account-count">{{ line }}</p>

          <div class="account-actions">
            <button
              type="button"
              class="check-now"
              :disabled="!a.enabled || running || starting"
              @click="checkNow"
            >
              Check now
            </button>
            <button
              type="button"
              class="change-password"
              :disabled="Boolean(busy[a.id])"
              :aria-expanded="pwFor === a.id ? 'true' : 'false'"
              @click="pwFor === a.id ? closePassword() : openPassword(a)"
            >
              Change app password
            </button>
            <button
              type="button"
              class="ghost disconnect"
              :disabled="Boolean(busy[a.id])"
              @click="askDisconnect(a)"
            >
              Disconnect
            </button>
          </div>

          <form
            v-if="pwFor === a.id"
            class="password-form"
            novalidate
            @submit.prevent="savePassword(a)"
            @keydown.esc="closePassword"
          >
            <label :for="`mail-new-password-${a.id}`">App password</label>
            <div class="row">
              <input
                :id="`mail-new-password-${a.id}`"
                type="password"
                autocomplete="off"
                spellcheck="false"
                :aria-describedby="`mail-new-password-help-${a.id}`"
                @input="pwFilled = $event.target.value.length > 0"
              >
              <button type="submit" class="primary password-save" :disabled="!pwFilled || Boolean(busy[a.id])">
                {{ busy[a.id] === 'password' ? 'Checking the login…' : 'Save' }}
              </button>
              <button type="button" class="ghost password-cancel" :disabled="busy[a.id] === 'password'" @click="closePassword">
                Cancel
              </button>
            </div>
            <p :id="`mail-new-password-help-${a.id}`" class="help">
              A 16-character code from your Google Account (it needs 2-Step Verification). Your normal
              Google password won't work.
              <a :href="APP_PASSWORDS_URL" target="_blank" rel="noopener noreferrer">Create an app password</a>
            </p>
          </form>

          <div
            v-if="confirming === a.id"
            class="confirm disconnect-confirm"
            role="group"
            :aria-labelledby="`mail-disconnect-title-${a.id}`"
            :aria-describedby="`mail-disconnect-body-${a.id}`"
            @keydown.esc="keepConnected(a)"
          >
            <p :id="`mail-disconnect-title-${a.id}`" class="confirm-title">Disconnect {{ a.address }}?</p>
            <p :id="`mail-disconnect-body-${a.id}`" class="confirm-body">{{ disconnectBody(a) }}</p>
            <div class="confirm-buttons">
              <button type="button" class="danger disconnect-yes" :disabled="busy[a.id] === 'disconnect'" @click="disconnect(a)">
                Disconnect
              </button>
              <button type="button" class="disconnect-no" @click="keepConnected(a)">Keep connected</button>
            </div>
          </div>

          <p v-if="rowError[a.id]" class="notice error row-error" role="alert">{{ rowError[a.id] }}</p>
        </li>
      </ul>

      <p v-if="checkError" class="notice error check-error" role="alert">{{ checkError }}</p>

      <div class="mail-connect">
        <div class="consent">
          <p class="consent-text">{{ consent.text }}</p>
          <label class="consent-box">
            <input v-model="consented" type="checkbox" class="consent-input">
            <span>Read this mailbox for application updates</span>
          </label>
        </div>

        <div v-if="offerApp" class="app-mailbox">
          <p class="app-mailbox-text">
            <strong>Your application mailbox</strong> · {{ mail.application_mailbox.address }} is already
            set up for email verification, so no password is needed.
          </p>
          <button
            type="button"
            class="primary use-app"
            :disabled="!consented || Boolean(connecting)"
            @click="useApp"
          >
            {{ connecting === 'app' ? 'Checking the login…' : 'Use this mailbox' }}
          </button>
          <p v-if="appError" class="notice error app-error" role="alert">{{ appError }}</p>
        </div>

        <form class="another" novalidate @submit.prevent="connect">
          <p v-if="offerApp" class="another-title">Another Gmail</p>
          <div class="field">
            <label for="mail-address">Gmail address</label>
            <input id="mail-address" v-model="address" type="email" autocomplete="off" spellcheck="false">
          </div>
          <div class="field">
            <label for="mail-app-password">App password</label>
            <input
              id="mail-app-password"
              ref="pwInput"
              type="password"
              autocomplete="off"
              spellcheck="false"
              aria-describedby="mail-app-password-help"
            >
            <p id="mail-app-password-help" class="help">
              A 16-character code from your Google Account (it needs 2-Step Verification). Your normal
              Google password won't work.
              <a :href="APP_PASSWORDS_URL" target="_blank" rel="noopener noreferrer">Create an app password</a>
            </p>
          </div>
          <div>
            <button type="submit" class="primary connect" :disabled="!consented || Boolean(connecting)">
              {{ connecting === 'other' ? 'Checking the login…' : 'Connect mailbox' }}
            </button>
          </div>
          <p v-if="connectError" class="notice error connect-error" role="alert">{{ connectError }}</p>
        </form>
      </div>
    </template>
  </div>
</template>

<style scoped>
.mail-card { display: grid; gap: var(--space-3); max-width: 40rem; padding: var(--space-4); }
.mail-title { margin: 0; font-size: var(--text-md); font-weight: 650; }
.mail-intro { margin: 0; color: var(--text-2); font-size: var(--text-sm); text-wrap: pretty; }
.not-offered { margin: 0; font-size: var(--text-sm); }
.notice { margin: 0; }

.mail-accounts { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.mail-account {
  display: grid; gap: var(--space-2); padding: var(--space-3);
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius);
}
.account-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2) var(--space-3); }
.account-address { font-weight: 600; overflow-wrap: anywhere; }
.account-status, .account-message, .account-count { margin: 0; font-size: var(--text-sm); color: var(--text-2); }
.account-status.failed { color: var(--danger); }
.account-notes { margin: 0; padding: 0; list-style: none; display: grid; gap: var(--space-1); }
.account-note { font-size: var(--text-sm); color: var(--warn); }
.account-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }

/* "Read this mailbox": a checkbox drawn as a switch; the input stays focusable. */
.switch { position: relative; display: inline-flex; align-items: center; gap: var(--space-2); cursor: pointer; font-size: var(--text-sm); }
.switch-input { position: absolute; opacity: 0; width: 2.25rem; height: 1.25rem; margin: 0; cursor: pointer; }
.switch-track {
  position: relative; flex: none; width: 2.25rem; height: 1.25rem; border-radius: 999px;
  background: var(--surface-3); border: 1px solid var(--border-strong); transition: background-color 0.12s;
}
.switch-thumb {
  position: absolute; top: 1px; left: 1px; width: calc(1.25rem - 4px); height: calc(1.25rem - 4px);
  border-radius: 50%; background: var(--surface); box-shadow: var(--shadow-sm); transition: transform 0.12s;
}
.switch-input:checked + .switch-track { background: var(--accent); border-color: var(--accent); }
.switch-input:checked + .switch-track .switch-thumb { transform: translateX(1rem); }
.switch-input:focus-visible + .switch-track { outline: 2px solid var(--focus); outline-offset: 2px; }
.switch-input:disabled + .switch-track { opacity: 0.6; }

.password-form { display: grid; gap: var(--space-2); }
.password-form label, .field label { font-weight: 600; font-size: var(--text-sm); }
.row { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; }
.help { margin: 0; color: var(--muted); font-size: var(--text-sm); }

.confirm { display: grid; gap: var(--space-2); padding: var(--space-3); background: var(--warn-soft); border-radius: var(--radius); }
.confirm p { margin: 0; font-size: var(--text-sm); }
.confirm-title { font-weight: 650; }
.confirm-buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }
button.danger { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, transparent); }

.mail-connect { display: grid; gap: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--border); }
.consent { display: grid; gap: var(--space-2); }
.consent-text { margin: 0; font-size: var(--text-sm); color: var(--text-2); text-wrap: pretty; }
.consent-box { display: inline-flex; align-items: center; gap: var(--space-2); font-weight: 600; font-size: var(--text-sm); cursor: pointer; }
.app-mailbox { display: grid; gap: var(--space-2); justify-items: start; }
.app-mailbox-text { margin: 0; font-size: var(--text-sm); }
.another { display: grid; gap: var(--space-3); }
.another-title { margin: 0; font-weight: 650; font-size: var(--text-sm); }
.field { display: grid; gap: var(--space-1); }

/* The global control style covers text, search and number; these two match it. */
input[type='email'], input[type='password'] {
  min-height: var(--control-h); max-width: 24rem; width: 100%;
  padding: 0 var(--space-3);
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  transition: border-color 0.12s, box-shadow 0.12s;
}
input[type='email']:hover, input[type='password']:hover { border-color: var(--muted); }
.password-form input[type='password'] { flex: 1 1 14rem; }
</style>
