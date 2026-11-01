// One toast at a time (M13-T2): the confirmation after an action, with the way
// back. "Moved to Applications - Undo · View", the way Gmail and LinkedIn
// confirm a move instead of asking "are you sure?" first. The shell renders it
// (ToastHost.vue); any tab can raise it.
//
// H1-4 (WCAG 2.2.1, Timing Adjustable): a toast that offers an action stays up
// longer; hovering it or moving focus into it pauses its timer, and leaving
// gives back the time that was left. A newer toast replacing one with an
// action keeps that action one step back (`previous`, "Undo previous"), so
// fast triage - S, S, S - never silently loses an Undo.
import { reactive } from 'vue'

export const TOAST_MS = 6000
export const ACTION_TOAST_MS = 10000

export const toast = reactive({ current: null })

let timer = null
let seq = 0
let deadline = 0          // when the running timer fires (Date.now() ms)
let remaining = 0         // what was left when it was paused
let paused = false
// Why it is paused. Kept apart because a replacement toast is a new element:
// the pointer may still be over it (no new mouseenter fires), but the button
// that had focus went away with the old one.
const holds = { hover: false, focus: false }

function arm(id, ms) {
  clearTimeout(timer)
  deadline = Date.now() + ms
  timer = setTimeout(() => dismissToast(id), ms)
}

// message: the sentence. action: { label, run } - a button (Undo). link:
// { label, href } - somewhere to go (View). timeout 0 keeps it until closed;
// by default a toast with an action gets ACTION_TOAST_MS, others TOAST_MS.
export function showToast({ message, action = null, link = null, timeout }) {
  clearTimeout(timer)
  timer = null
  paused = false
  holds.focus = false                       // the focused button left with the old toast
  const before = toast.current
  const previous = before?.action ? { message: before.message, action: before.action } : null
  const id = ++seq
  toast.current = { id, message, action, link, previous, timed: false }
  const ms = timeout ?? (action ? ACTION_TOAST_MS : TOAST_MS)
  if (ms) {
    toast.current.timed = true
    if (holds.hover) {                      // still under the pointer: start paused
      paused = true
      remaining = ms
    } else {
      arm(id, ms)
    }
  }
  return id
}

// Without an id, closes whatever is showing; with one, only that toast.
export function dismissToast(id) {
  if (id === undefined || toast.current?.id === id) {
    clearTimeout(timer)
    timer = null
    paused = false
    holds.hover = false
    holds.focus = false
    toast.current = null
  }
}

// Hover ('hover') or focus ('focus') inside the toast: stop the clock.
export function pauseToast(why = 'hover') {
  holds[why] = true
  if (!toast.current?.timed || paused) return
  paused = true
  remaining = Math.max(0, deadline - Date.now())
  clearTimeout(timer)
  timer = null
}

// That hover or focus is gone: once nothing holds the toast, the time that
// was left runs again, from now.
export function resumeToast(why = 'hover') {
  holds[why] = false
  if (!toast.current?.timed || !paused || holds.hover || holds.focus) return
  paused = false
  arm(toast.current.id, remaining)
}

// "Undo previous" was used: that step back is gone, the toast stays.
export function dropPrevious(id) {
  if (toast.current?.id === id) toast.current = { ...toast.current, previous: null }
}
