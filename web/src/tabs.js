// The tab registry (PRD 8.5). Adding a tab is one entry here plus one component
// file in ./tabs/ - App.vue renders whatever this lists and is never edited for
// a new tab (M7-T4 proves it). The entry's `id` is also its URL: `#/<id>`.
//
// Every tab component receives the same props from the shell and may emit the
// same events - see ./shell.js, which a tab uses as
//   defineProps(tabProps); defineEmits(tabEmits)
//
// `badge` (optional) turns the shell's data - { jobs, stats, runs, run,
// detailsNeeded, attention } - into a count shown on the tab, or null for none. `badgeLabel`
// says what it counts, for screen readers. `goKey` (optional) is the letter of
// the go-to shortcut "g <letter>" (shortcuts.js). `quiet` draws the tab less
// prominently and apart from the rest (Q-75 N19).
//
// Q-100 (design §1, A14): `badgeTone: 'attention'` draws the count amber - it
// says something is wrong, not "there is work"; the shell's data then also
// carries `attention` (connections that need the owner, connections.js §2.2).
// `bar: true` puts the tab in the phone's bottom bar (under 640px), drawn with
// its `icon` (Icon.vue); the others open from the bar's More sheet, in this order.
import { activeApplicationCount, newRoleCount } from './badges.js'

export const TABS = [
  // The home page, and so the default route (`tabFromHash` falls back to the first tab).
  { id: 'overview', label: 'Overview', component: () => import('./tabs/Overview.vue'), goKey: 'o', bar: true, icon: 'layers' },
  {
    id: 'inbox', label: 'Inbox', component: () => import('./tabs/Inbox.vue'),
    badge: ({ jobs }) => newRoleCount(jobs), badgeLabel: 'new roles', goKey: 'i', bar: true, icon: 'inbox',
  },
  {
    id: 'applications', label: 'Applications', component: () => import('./tabs/Applications.vue'),
    badge: ({ stats }) => (stats ? activeApplicationCount(stats.by_status) : null), badgeLabel: 'active', goKey: 'a',
    bar: true, icon: 'briefcase',
  },
  { id: 'runs', label: 'Runs', component: () => import('./tabs/Runs.vue'), goKey: 'r' },
  { id: 'companies', label: 'Companies', component: () => import('./tabs/Companies.vue'), goKey: 'c' },
  // The badge counts the details auto-apply is waiting for (Q-127 B.4, D-215): the length of
  // `details_needed` in GET /api/apply/status, which the shell already reads. Never a count of
  // questions, assumed answers or saved answers: the Profile page shows none of those.
  {
    id: 'profile', label: 'Profile', component: () => import('./tabs/Profile.vue'),
    badge: ({ detailsNeeded }) => detailsNeeded, badgeLabel: 'details needed', goKey: 'p',
  },
  // The badge counts connections that need the owner (Q-100 §1): none when the
  // count is 0 or the connections could not be loaded.
  {
    id: 'settings', label: 'Settings', component: () => import('./tabs/Settings.vue'), goKey: 's',
    badge: ({ attention }) => attention, badgeLabel: 'need attention', badgeTone: 'attention',
  },
  // The background job and its log (M16) - for the owner of this install. Last,
  // and drawn quietly: it is not part of the daily loop (Q-75 N19).
  { id: 'developer', label: 'Developer', component: () => import('./tabs/Developer.vue'), goKey: 'd', quiet: true },
]
