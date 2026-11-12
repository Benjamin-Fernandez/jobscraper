// The reads behind Settings -> Apply (Q-116 design §2, §7): the apply status, the
// editable settings and the application-details summary, fetched together. Reuses the
// Q-100 client (connections_api.js); it adds no route and never sends a PUT, so loading
// the page can't pin `apply.*` rows over config.yaml.
//
// Each part is null when its call failed or the server lacks the route (a 404/405 is
// already `null` in the client), so the page hides what it can't read instead of
// faking it. One failure never costs the others.
import { getApplySettings, getApplicantSummary, getApplyStatus } from './connections_api.js'
import { findItem } from './applicantForm.js'

// -> { status: {mode, missing, busy}|null, settings: {mode, writable, ...}|null,
//      summary: {missing, completeness, form}|null }
export async function loadApplyData() {
  const [status, settings, summary] = await Promise.all([
    getApplyStatus().catch(() => null),
    getApplySettings().catch(() => null),
    getApplicantSummary().catch(() => null),
  ])
  return { status: status ?? null, settings: settings ?? null, summary: summary ?? null }
}

// The distinct labels of the application details still missing, in the order the
// server lists them ("Phone number", "Work rights"). A path the form schema doesn't
// know shows as the path itself. [] when there is nothing missing or no summary.
export function missingLabels(summary) {
  const form = summary?.form
  const seen = new Set()
  const out = []
  for (const path of Array.isArray(summary?.missing) ? summary.missing : []) {
    const label = String(findItem(form, path)?.label || path)
    if (!seen.has(label)) {
      seen.add(label)
      out.push(label)
    }
  }
  return out
}
