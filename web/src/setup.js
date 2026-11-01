// Getting started (UX-1): what a run needs before it can find anything, in the
// order a new user does it. Each step is done when the thing it asks for already
// exists; the checklist in the empty Inbox (SetupChecklist.vue) draws these.

// { hasResume, titleCount, companyCount, runCount } -> [{id, label, hint, href, cta, done}]
export function setupSteps({ hasResume = false, titleCount = 0, companyCount = 0, runCount = 0 } = {}) {
  return [
    {
      id: 'resume', label: 'Upload your resume', href: '#/profile', cta: 'Upload',
      hint: 'PDF or DOCX. Your skills and the roles you fit are read from it.',
      done: Boolean(hasResume),
    },
    {
      id: 'titles', label: 'Choose the job titles to search for', href: '#/profile', cta: 'Choose titles',
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
}
