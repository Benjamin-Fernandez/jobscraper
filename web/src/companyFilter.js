// "N failed" in the run history opens the Companies tab on its Failed list.
// A one-shot request, like the Runs picker's (runs.js): a plain visit to the
// Companies tab starts on All as usual.
let wanted = null
export function requestCompanyFilter(filter) {
  wanted = filter
}
export function takeCompanyFilter() {
  const filter = wanted
  wanted = null
  return filter
}
