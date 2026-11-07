// The words of the "Private" tag (D-105, docs/architecture/q74_model_sees_sensitive.md §5).
//
// The tag says where a private value goes. With the owner's switch on and the
// model running on this computer (the server's effective `model_sees_private`,
// never the config key), the local AI may read it; otherwise it is kept from the
// AI. Either way it is never written to logs. One module, so the Details form,
// the question cards and the inbox always say the same thing.
import { ref } from 'vue'

const OFF_BADGE = 'Private: never sent to the AI'
const ON_BADGE = 'Private: local AI only'
const ON_SENTENCE = "Private. Only the AI on this computer reads it, and it's never written to logs."

// The last effective value a Questions payload carried. QuestionsInbox sets it
// when it loads, so a QuestionCard (which gets no payload of its own) follows it.
export const modelSeesPrivate = ref(false)

export function setModelSeesPrivate(on) {
  modelSeesPrivate.value = !!on
}

// The short tag text. `on` defaults to the last payload's value.
export function privateBadge(on = modelSeesPrivate.value) {
  return on ? ON_BADGE : OFF_BADGE
}

// The full sentence for a title or a screen reader (off: the tag text, unchanged).
export function privateSentence(on = modelSeesPrivate.value) {
  return on ? ON_SENTENCE : OFF_BADGE
}
