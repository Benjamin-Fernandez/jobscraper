// The tab registry (PRD 8.5). Adding a tab is one entry here plus one component
// file in ./tabs/ - App.vue renders whatever this lists and is never edited for
// a new tab (M7-T4 proves it).
//
// Every tab component receives the same props from the shell:
//   run   - the selected run: a number, or 'all'
//   jobs  - that run's shortlist, each job carrying its application `status`
// and may emit `changed` to ask the shell to reload the dataset.
export const TABS = [
  { id: 'inbox', label: 'Inbox', component: () => import('./tabs/Inbox.vue') },
]
