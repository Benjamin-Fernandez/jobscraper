// The contract between the shell (App.vue) and every tab. A tab component
// declares these so the shell can hand every tab the same things without any
// of them leaking onto the tab's root element as stray attributes:
//
//   defineProps(tabProps)
//   defineEmits(tabEmits)
//
// Props - the shared dataset the shell owns:
//   run      the selected run: a number, or 'all'
//   runs     the run list, newest first (GET /api/runs)
//   jobs     that run's shortlist, each job carrying its application `status`
//   loading  the shortlist is being fetched
//   error    why the shortlist could not be fetched, or ''
// Events:
//   changed      reload the dataset; `{ runs: true }` reloads the run list too
//                (a run just finished) and follows the newest run
//   select-run   show another run (a number or 'all')
export const tabProps = {
  run: { type: [Number, String], default: null },
  runs: { type: Array, default: () => [] },
  jobs: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
}

export const tabEmits = ['changed', 'select-run']
