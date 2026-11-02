<script setup>
// "From your email" (Q-60, F-50l, F-50n; mail_status_design.md sections 8 and
// 11): the status updates JobScraper read in email but wasn't sure enough to
// make on its own. Each one says what the email says, quotes the line it came
// from and why it is asking; the owner sets it, dismisses it or opens the email.
//
// - A suggestion with a target: "Set to {Status}" (accept) and "Dismiss".
// - Without one ("Check the email"): "Got it" only, which dismisses it.
// - Several applications at the employer fit: the owner picks one first. Nothing
//   is preselected, because the system never picks for them (MS section 8 row 4).
//
// Hidden when there is nothing to show, and when the server has no such route.
// Emits `changed` after an accepted suggestion so the tab reloads its rows.
import { onMounted, ref } from 'vue'
import { acceptMailSuggestion, describeError, dismissMailSuggestion, getMailSuggestions, mailProblem } from '../api.js'
import { shortDate } from '../format.js'
import { statusLabel } from '../stages.js'

const emit = defineEmits(['changed'])

const ACCEPT_CONFLICT = 'This application changed after the email. Set the status by hand if you still want this.'

const items = ref([])
const busy = ref({})          // suggestion id -> 'accept' | 'dismiss'
const errors = ref({})        // suggestion id -> text
const picked = ref({})        // suggestion id -> the job id chosen for an ambiguous one

const patch = (target, key, v) => { target.value = { ...target.value, [key]: v } }

async function load() {
  try {
    const r = await getMailSuggestions()
    items.value = Array.isArray(r?.suggestions) ? r.suggestions : []
  } catch {
    // No route on this server, or a blip: keep what is shown; the next action reloads.
  }
}

// (A function, not `patch` in the template: there the ref arrives unwrapped.)
function pick(s, jobId) {
  patch(picked, s.id, jobId)
}

const ambiguous = s => Array.isArray(s.candidates) && s.candidates.length > 0
const appLine = s => [s.company, s.role].filter(Boolean).join(' · ')
const candidateLabel = c => `${c.role || c.job_id} · ${statusLabel(c.status)}`

// The link the server builds to the owner's own Gmail (MS section 11.1); never one from mail.
function gmailHref(s) {
  return /^https:\/\/mail\.google\.com\//.test(s.gmail_url || '') ? s.gmail_url : null
}

async function accept(s) {
  if (busy.value[s.id]) return
  const jobId = ambiguous(s) ? picked.value[s.id] : undefined
  if (ambiguous(s) && !jobId) return
  patch(busy, s.id, 'accept')
  patch(errors, s.id, '')
  try {
    const r = await acceptMailSuggestion(s.id, jobId)
    emit('changed', { jobId: jobId ?? s.job_id, status: r?.status ?? s.to_status })
    await load()
  } catch (e) {
    const p = mailProblem(e)
    patch(errors, s.id, p.status === 409 ? ACCEPT_CONFLICT : `Could not set it: ${p.detail || describeError(e)}`)
  } finally {
    patch(busy, s.id, '')
  }
}

async function dismiss(s) {
  if (busy.value[s.id]) return
  patch(busy, s.id, 'dismiss')
  patch(errors, s.id, '')
  try {
    await dismissMailSuggestion(s.id)
    await load()
  } catch (e) {
    const p = mailProblem(e)
    patch(errors, s.id, `Could not dismiss it: ${p.detail || describeError(e)}`)
  } finally {
    patch(busy, s.id, '')
  }
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <section v-if="items.length" class="mail-suggestions surface" aria-labelledby="mail-suggestions-title">
    <header class="ms-head">
      <h3 id="mail-suggestions-title" class="ms-title">
        From your email <span class="ms-count num">{{ items.length }}</span>
      </h3>
      <p class="ms-sub">Updates JobScraper wasn't sure enough to make.</p>
    </header>
    <ul class="ms-items">
      <li
        v-for="s in items"
        :key="s.id"
        class="ms-item"
        :data-suggestion="s.id"
        :data-job="s.job_id ?? ''"
        :data-reason="s.reason"
      >
        <p class="ms-app">{{ appLine(s) }}</p>
        <p class="ms-says">
          <template v-if="s.to_status">
            Email says: <span class="pill" :data-status="s.to_status">{{ statusLabel(s.to_status) }}</span>
          </template>
          <template v-else>Check the email</template>
        </p>
        <blockquote v-if="s.quote" class="ms-quote">“{{ s.quote }}”</blockquote>
        <p class="ms-from">{{ [s.sender_domain, shortDate(s.received_at)].filter(Boolean).join(' · ') }}</p>
        <p v-if="s.reason_text" class="ms-reason">{{ s.reason_text }}</p>

        <label v-if="s.to_status && ambiguous(s)" class="ms-which">
          <span>Which application?</span>
          <select
            class="ms-pick"
            :value="picked[s.id] ?? ''"
            :disabled="Boolean(busy[s.id])"
            @change="pick(s, $event.target.value)"
          >
            <option value="" disabled>Choose…</option>
            <option v-for="c in s.candidates" :key="c.job_id" :value="c.job_id">{{ candidateLabel(c) }}</option>
          </select>
        </label>

        <div class="ms-actions">
          <template v-if="s.to_status">
            <button
              type="button"
              class="primary ms-accept"
              :disabled="Boolean(busy[s.id]) || (ambiguous(s) && !picked[s.id])"
              @click="accept(s)"
            >
              Set to {{ statusLabel(s.to_status) }}
            </button>
            <button type="button" class="ms-dismiss" :disabled="Boolean(busy[s.id])" @click="dismiss(s)">Dismiss</button>
          </template>
          <button v-else type="button" class="ms-got-it" :disabled="Boolean(busy[s.id])" @click="dismiss(s)">Got it</button>
          <a
            v-if="gmailHref(s)"
            class="button ghost ms-gmail"
            :href="gmailHref(s)"
            target="_blank"
            rel="noopener noreferrer"
          >Open in Gmail</a>
        </div>
        <p v-if="errors[s.id]" class="notice error ms-error" role="alert">{{ errors[s.id] }}</p>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.mail-suggestions { margin-bottom: var(--space-4); padding: var(--space-3) var(--space-4); }
.ms-head { margin-bottom: var(--space-2); }
.ms-title { display: flex; align-items: center; gap: var(--space-2); margin: 0; font-size: var(--text-md); font-weight: 650; }
.ms-count {
  min-width: 1.6em; padding: 0 0.35em; border-radius: 999px; text-align: center;
  font-size: var(--text-xs); line-height: 1.6; color: var(--accent-text); background: var(--accent);
}
.ms-sub { margin: 2px 0 0; color: var(--muted); font-size: var(--text-sm); }
.ms-items { list-style: none; margin: 0; padding: 0; }
.ms-item { display: grid; gap: var(--space-1); padding: var(--space-3) 0; border-top: 1px solid var(--border); }
.ms-item p { margin: 0; font-size: var(--text-sm); }
.ms-app { font-weight: 600; color: var(--text); overflow-wrap: anywhere; }
.ms-says { display: flex; align-items: center; gap: var(--space-2); color: var(--text-2); }
.ms-quote {
  margin: 0; padding-left: var(--space-3); border-left: 2px solid var(--border-strong);
  color: var(--text); font-size: var(--text-sm); overflow-wrap: anywhere;
}
.ms-from { color: var(--muted); }
.ms-reason { color: var(--text-2); }
.ms-which { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); font-size: var(--text-sm); font-weight: 600; }
.ms-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-1); }
.ms-error { margin: var(--space-1) 0 0; }
</style>
