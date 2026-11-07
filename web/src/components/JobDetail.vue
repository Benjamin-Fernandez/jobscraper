<script setup>
// One posting in full (Q-76): the head, the facts, "Why it matches", the matched
// skills and "About the job". Extracted from the Inbox's detail pane so the
// Applications tab shows the same thing. The caller owns what surrounds it: the
// Inbox puts its action bar in the `actions` slot (after the closed note), the
// Applications row puts the attempts list in `extra` (at the end).
//
// `job` has the shortlist's shape ({id, title, company, location, yoe_min,
// decided_at, closed, url, reason, matched_skills}); a field it lacks (a role that
// left the shortlist) just leaves its block out. The description is fetched when
// the component opens, through the shared postingCache.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { cleanLocation, plural, shortDate } from '../format.js'
import { parseDescription, previewBlocks } from '../jd.js'
import { holdPostings, loadPosting, postingEntry, releasePostings } from '../postingCache.js'
import CompanyMark from './CompanyMark.vue'
import Icon from './Icon.vue'

const props = defineProps({
  job: { type: Object, required: true },
  titleId: { type: String, default: 'detail-title' },
})

const PREVIEW_CHARS = 1400
const expanded = ref(false)

function years(job) {
  if (job.yoe_min === null || job.yoe_min === undefined) return null
  return job.yoe_min === 0 ? 'No experience required' : `${plural(job.yoe_min, 'year')} experience`
}

const description = computed(() => postingEntry(props.job.id))
// Headings, lists and paragraphs, cut to a preview at a block boundary until Show more.
const descriptionBlocks = computed(() => parseDescription(description.value?.text))
const descriptionPreview = computed(() => previewBlocks(descriptionBlocks.value, PREVIEW_CHARS))
const descriptionShown = computed(() => (expanded.value ? descriptionBlocks.value : descriptionPreview.value.blocks))

holdPostings()
onBeforeUnmount(releasePostings)

watch(() => props.job.id, id => {
  expanded.value = false
  if (id && !postingEntry(id)) loadPosting(id)
}, { immediate: true })
</script>

<template>
  <div class="job-detail">
    <header class="detail-head">
      <CompanyMark :name="job.company" size="lg" />
      <div class="detail-names">
        <h3 :id="titleId" class="detail-title" tabindex="-1">{{ job.title }}</h3>
        <p class="detail-company">{{ job.company }}</p>
      </div>
    </header>

    <ul class="facts">
      <li v-if="job.location"><Icon name="pin" /> {{ cleanLocation(job.location) }}</li>
      <li v-if="years(job)"><Icon name="briefcase" /> {{ years(job) }}</li>
      <li v-if="job.decided_at"><Icon name="clock" /> Found {{ shortDate(job.decided_at) }}</li>
    </ul>

    <p v-if="job.closed" class="notice warn stale-note">
      This posting has been taken down on the company's site.
    </p>

    <slot name="actions" />

    <section v-if="job.reason" class="why">
      <h4><Icon name="target" /> Why it matches</h4>
      <p class="reason">{{ job.reason }}</p>
    </section>

    <section v-if="job.matched_skills && job.matched_skills.length" class="why">
      <h4>Matched skills</h4>
      <ul class="skills" aria-label="Matched skills">
        <li v-for="skill in job.matched_skills" :key="skill" class="chip">{{ skill }}</li>
      </ul>
    </section>

    <section class="why jd">
      <h4><Icon name="briefcase" /> About the job</h4>
      <p class="visually-hidden" role="status">{{ description?.state === 'error' ? 'Could not load the description.' : '' }}</p>
      <p v-if="!description || description.state === 'loading'" class="muted jd-status">Loading the description…</p>
      <p v-else-if="description.state === 'error'" class="muted jd-status">
        Could not load the description ({{ description.error }}). It is on the company site.
      </p>
      <p v-else-if="!description.text" class="muted jd-status">
        The job board gave no description for this role - read it on the company site.
      </p>
      <template v-else>
        <div class="jd-text">
          <template v-for="(block, i) in descriptionShown" :key="i">
            <h5 v-if="block.type === 'heading'" class="jd-h">{{ block.text }}</h5>
            <ul v-else-if="block.type === 'list'" class="jd-list">
              <li v-for="(item, k) in block.items" :key="k">{{ item }}</li>
            </ul>
            <p v-else class="jd-p">{{ block.text }}</p>
          </template>
        </div>
        <button
          v-if="descriptionPreview.cut"
          type="button"
          class="link jd-more"
          @click="expanded = !expanded"
        >{{ expanded ? 'Show less' : 'Show more' }}</button>
      </template>
    </section>

    <slot name="extra" />
  </div>
</template>

<style scoped>
.detail-head { display: flex; align-items: center; gap: var(--space-4); }
.detail-names { min-width: 0; }
.detail-title { margin: 0; font-size: var(--text-xl); font-weight: 650; letter-spacing: -0.01em; }
.detail-company { margin: var(--space-1) 0 0; color: var(--text-2); font-weight: 500; }

.facts {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-5);
  margin: var(--space-4) 0 0;
  padding: 0;
  color: var(--text-2);
  font-size: var(--text-sm);
}
.facts li { display: inline-flex; align-items: center; gap: var(--space-2); }
.facts .icon { color: var(--muted); }
.stale-note { margin: var(--space-4) 0 0; }

.why { margin-top: var(--space-5); }
.why h4 {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-2);
  font-size: var(--text-xs);
  font-weight: 650;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}
.reason { margin: 0; max-width: 68ch; color: var(--text); }
.skills { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: var(--space-1); }
/* The description as the employer wrote it: its own line breaks, readable width. */
.jd { padding-top: var(--space-4); border-top: 1px solid var(--border); }
.jd-text {
  overflow-wrap: anywhere; max-width: 72ch;
  font-size: var(--text-sm); line-height: 1.65; color: var(--text);
}
.jd-text > :first-child { margin-top: 0; }
.jd-h { margin: var(--space-4) 0 var(--space-1); font-size: var(--text-sm); font-weight: 650; text-wrap: balance; }
.jd-p { margin: 0 0 var(--space-2); white-space: pre-line; text-wrap: pretty; }
.jd-list { margin: 0 0 var(--space-2); padding-left: 1.25rem; }
.jd-list li + li { margin-top: 2px; }
.jd-list li::marker { color: var(--muted); }
.jd-status { margin: 0; font-size: var(--text-sm); }
.jd-more { margin-top: var(--space-2); font-size: var(--text-sm); }
</style>
