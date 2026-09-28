// One toast at a time (M13-T2): the confirmation after an action, with the way
// back. "Moved to Applications - Undo · View", the way Gmail and LinkedIn
// confirm a move instead of asking "are you sure?" first. The shell renders it
// (ToastHost.vue); any tab can raise it.
import { reactive } from 'vue'

export const TOAST_MS = 6000

export const toast = reactive({ current: null })

let timer = null
let seq = 0

// message: the sentence. action: { label, run } - a button (Undo). link:
// { label, href } - somewhere to go (View). timeout 0 keeps it until closed.
export function showToast({ message, action = null, link = null, timeout = TOAST_MS }) {
  clearTimeout(timer)
  const id = ++seq
  toast.current = { id, message, action, link }
  if (timeout) timer = setTimeout(() => dismissToast(id), timeout)
  return id
}

// Without an id, closes whatever is showing; with one, only that toast.
export function dismissToast(id) {
  if (id === undefined || toast.current?.id === id) {
    clearTimeout(timer)
    toast.current = null
  }
}
