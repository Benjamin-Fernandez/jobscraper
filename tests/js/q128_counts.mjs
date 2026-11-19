// Q-128 helper for tests/test_q128.py: the web half of "the three counts agree".
// Reads the server's real payload ({missing, needed_by, form}) from the JSON file in argv[2] and prints
// {tab, line, labels}: what the Profile tab label counts (Profile.vue::probeCounts) and what the status
// line says (detailSections.statusLine over detailsNeeded), computed by the REAL web/src functions.
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const mod = await import(pathToFileURL(resolve(here, '../../web/src/detailSections.js')).href)
const { missing, needed_by: neededBy, form } = JSON.parse(readFileSync(process.argv[2], 'utf8'))

const needed = mod.detailsNeeded(missing, neededBy, form)
const line = mod.statusLine({ form, needed })
process.stdout.write(JSON.stringify({ tab: needed.length, line: line.count, labels: line.labels }))
