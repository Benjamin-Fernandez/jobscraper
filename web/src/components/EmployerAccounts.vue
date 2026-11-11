<script setup>
// The employer accounts JobScraper holds (Q-100 design §4.1, Wave 1): one row per
// `ats_accounts` row from GET /api/connections - site, email, state, whether the
// account was verified, how the last sign-in went, when it was created.
//
// Read-only. A row that needs the owner shows the exact command line behind "See how
// to fix"; the command prompts for the password itself. Nothing here shows, copies
// or asks for a password (D-191), and the server never sends one. The Wave 2 buttons
// (Enter password, Open sign-in page, Forget) are deliberately absent: the help text
// stands in for them. The email is shown in full (D-193).
//
// Wide screens get a table; at 640px and under each row becomes a block, with the
// column names beside the values.
import { COPY, codeCopy } from '../connections.js'
import { shortDate } from '../format.js'
import StateChip from './StateChip.vue'

defineProps({
  accounts: { type: Array, default: () => [] },
  noAccountNeeded: { type: Array, default: () => ['greenhouse', 'lever', 'ashby'] },
})

const FIXABLE = new Set(['signin_failed', 'exists_no_password', 'password_missing'])

const needsFix = row => row.state === 'attention' && FIXABLE.has(row.code)
const command = row => `python -m jobscraper accounts add --url https://${row.tenant_host}/ --email ${row.email}`

function lastSignin(row) {
  if (!row.last_signin_at) return 'Not yet'
  const day = shortDate(row.last_signin_at)
  if (row.last_signin_ok === true) return `${day}, signed in`
  if (row.last_signin_ok === false) return `${day}, failed`
  return day
}

const names = list => list.map(n => n[0].toUpperCase() + n.slice(1)).join(', ')

// The Credential Manager hint has `code` spans marked with backticks.
const hintParts = COPY.readPassword.split('`').map((text, i) => ({ text, code: i % 2 === 1 }))
</script>

<template>
  <div class="employer-accounts">
    <p v-if="!accounts.length" class="muted employer-empty">{{ COPY.employerEmpty }}</p>
    <table v-else class="employer-table">
      <caption class="visually-hidden">Employer accounts</caption>
      <thead>
        <tr>
          <th scope="col">Site</th>
          <th scope="col">Email</th>
          <th scope="col">Status</th>
          <th scope="col">Last sign-in</th>
          <th scope="col">Created</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in accounts" :key="row.id">
          <tr class="employer-row" :data-account="row.id" :data-state="row.state">
            <td data-label="Site" class="cell-site">{{ row.tenant_host }}</td>
            <td data-label="Email" class="cell-email">{{ row.email }}</td>
            <td data-label="Status" class="cell-status">
              <StateChip :item="row" :label="row.tenant_host" />
              <span class="verified" :class="{ yes: row.verified_at }">
                {{ row.verified_at ? 'Verified' : 'Not verified' }}
              </span>
            </td>
            <td data-label="Last sign-in">{{ lastSignin(row) }}</td>
            <td data-label="Created">{{ shortDate(row.created_at) || '-' }}</td>
          </tr>
          <tr v-if="codeCopy(row) || needsFix(row)" class="employer-detail" :data-account="row.id">
            <td colspan="5">
              <p v-if="codeCopy(row)" class="employer-line">{{ codeCopy(row) }}</p>
              <details v-if="needsFix(row)" class="employer-fix">
                <summary>See how to fix</summary>
                <p class="employer-fix-note">
                  Run this in a terminal. It asks for the password, so the password never goes through this page.
                </p>
                <pre class="code-wrap">{{ command(row) }}</pre>
              </details>
            </td>
          </tr>
        </template>
      </tbody>
    </table>

    <p class="employer-note muted">
      No account needed: {{ names(noAccountNeeded) }}. {{ COPY.noAccountNeeded }}
    </p>
    <p class="employer-note muted">
      <template v-for="(p, i) in hintParts" :key="i"><code v-if="p.code">{{ p.text }}</code><template v-else>{{ p.text }}</template></template>
    </p>
  </div>
</template>

<style scoped>
.employer-accounts { display: grid; gap: var(--space-2); }
.employer-empty, .employer-note { margin: 0; font-size: var(--text-sm); text-wrap: pretty; }
.employer-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
.employer-table th {
  text-align: left; padding: var(--space-1) var(--space-2); color: var(--muted);
  font-weight: 600; border-bottom: 1px solid var(--border);
}
.employer-table td { padding: var(--space-2); vertical-align: top; }
.employer-row td { border-top: 1px solid var(--border); }
.employer-row:first-child td { border-top: 0; }
.employer-detail td { padding-top: 0; }
.cell-site, .cell-email { overflow-wrap: anywhere; }
.cell-status { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-2); }
.verified { color: var(--muted); }
.verified.yes { color: var(--ok); font-weight: 600; }
.employer-line { margin: 0; color: var(--text-2); text-wrap: pretty; }
.employer-fix summary {
  display: flex; align-items: center; min-height: 2rem; cursor: pointer;
  font-weight: 600; color: var(--accent);
}
.employer-fix summary:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
.employer-fix-note { margin: var(--space-1) 0; color: var(--text-2); }
code { font-family: var(--mono); font-size: var(--text-xs); }

@media (max-width: 640px) {
  .employer-table thead {
    position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%);
  }
  .employer-table, .employer-table tbody { display: block; }
  .employer-row, .employer-detail { display: grid; gap: var(--space-1); }
  .employer-row { padding: var(--space-2) 0; border-top: 1px solid var(--border); }
  .employer-row:first-child { border-top: 0; }
  .employer-row td { display: grid; grid-template-columns: 6.5rem 1fr; gap: var(--space-2); border: 0; padding: 0 var(--space-1); }
  .employer-row td::before { content: attr(data-label); color: var(--muted); font-weight: 600; }
  .employer-row .cell-status { display: grid; grid-template-columns: 6.5rem auto; align-items: center; }
  .employer-row .cell-status > * { grid-column: 2; }
  .employer-detail td { display: block; padding: 0 var(--space-1) var(--space-2); }
  .employer-fix summary { min-height: var(--touch-min); }
}
</style>
