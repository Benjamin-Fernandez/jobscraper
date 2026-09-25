// The tab registry (PRD 8.5). Adding a tab is one entry here plus one component
// file in ./tabs/ - App.vue renders whatever this lists and is never edited for
// a new tab (M7-T4 proves it). The entry's `id` is also its URL: `#/<id>`.
//
// Every tab component receives the same props from the shell and may emit the
// same events - see ./shell.js, which a tab uses as
//   defineProps(tabProps); defineEmits(tabEmits)
//
// `badge` (optional) turns the shell's data - { jobs, stats, runs, run } - into
// a count shown on the tab, or null for none. `badgeLabel` says what it counts,
// for screen readers.
import { activeApplicationCount, newRoleCount } from './badges.js'

export const TABS = [
  {
    id: 'inbox', label: 'Inbox', component: () => import('./tabs/Inbox.vue'),
    badge: ({ jobs }) => newRoleCount(jobs), badgeLabel: 'new roles',
  },
  {
    id: 'applications', label: 'Applications', component: () => import('./tabs/Applications.vue'),
    badge: ({ stats }) => (stats ? activeApplicationCount(stats.by_status) : null), badgeLabel: 'active',
  },
  { id: 'runs', label: 'Runs', component: () => import('./tabs/Runs.vue') },
  { id: 'profile', label: 'Profile', component: () => import('./tabs/Profile.vue') },
  { id: 'settings', label: 'Settings', component: () => import('./tabs/Settings.vue') },
]
