// Getting started (UX-1): what a run needs before it can find anything, in the
// order a new user does it. Each step is done when the thing it asks for already
// exists; the checklist (SetupChecklist.vue) draws these as part 1, "Find jobs",
// of the first-run setup (Q-100 design §4.2). Part 2, "Apply for me", is
// connections.js `applySteps`.
//
// Q-100 A6: the resume and titles steps open Profile on "Resume and titles"
// (`#/profile/resume`), not on whichever view Profile would pick by itself.
// Q-100 A7: a step whose check failed is 'unknown' - neither done nor to do -
// and is not counted, so a server blip never shows "0 of 4" to an established
// install.

const RESUME_HREF = '#/profile/resume'

// { hasResume, titleCount, companyCount, runCount, unknown } ->
//   [{id, label, hint, href, cta, done, status, required}]
// `unknown` lists the step ids whose check failed: status 'unknown', done false.
export function setupSteps({
  hasResume = false, titleCount = 0, companyCount = 0, runCount = 0, unknown = [],
} = {}) {
  const steps = [
    {
      id: 'resume', label: 'Upload your resume', href: RESUME_HREF, cta: 'Upload',
      hint: 'PDF or DOCX. Your skills and the roles you fit are read from it.',
      done: Boolean(hasResume),
    },
    {
      id: 'titles', label: 'Choose the job titles to search for', href: RESUME_HREF, cta: 'Choose titles',
      hint: 'Taken from your resume at first - add your own or ask for recommendations.',
      done: titleCount > 0,
    },
    {
      id: 'companies', label: 'Add the companies you want to work for', href: '#/companies', cta: 'Add companies',
      hint: 'Type or paste their names; each careers site is found for you.',
      done: companyCount > 0,
    },
    {
      id: 'run', label: 'Run your first search', href: '#/runs', cta: 'Start a run',
      hint: 'New roles that fit you land here, in your Inbox.',
      done: runCount > 0,
    },
  ]
  const failed = new Set(unknown)
  return steps.map(s => {
    if (failed.has(s.id)) return { ...s, required: true, done: false, status: 'unknown' }
    return { ...s, required: true, status: s.done ? 'done' : 'todo' }
  })
}

// "n of m" over a part's steps: REQUIRED steps whose check answered (Q-100 Res
// m2, A7). `allFailed`: none of the required steps could be checked.
export function countSteps(steps) {
  const required = steps.filter(s => s.required !== false)
  const counted = required.filter(s => s.status !== 'unknown' && s.status !== 'checking')
  return {
    done: counted.filter(s => s.done).length,
    total: counted.length,
    allFailed: required.length > 0 && counted.length === 0,
  }
}
