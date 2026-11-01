// Exporteert alle LikeC4 views naar PNG in ./exports en vervangt de oude bestanden.
// Gebruik (in de map architecture):  node export-views.mjs
// Vereist: Node 18+. LikeC4 wordt via npx gebruikt, dus geen aparte installatie nodig.

import { spawnSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const outDir = join(root, 'exports')

// view id in het .c4 bestand  ->  bestandsnaam in exports/
const views = {
  index: '1 - Context.png',
  ses: '2 - Container.png',
  webappDetail: '3.1 - Component Web app.png',
  frontendApiDetail: '3.2 - Component Frontend API.png',
  processingDetail: '3.3 - Component Data processing.png',
  trainingDetail: '3.4 - Component Ingest and training pipeline.png',
  forecastDetail: '3.5 - Component Forecast pipeline.png',
  backendApiDetail: '3.6 - Component Backend API.png',
  databaseDetail: '3.7 - Component Database.png',
  // components: '3 - Component All.png',   // haal de // weg om ook de overzichtsview te exporteren
}

// 1. Eerst naar een tijdelijke map, zodat de oude exports intact blijven als het misgaat
const tmp = mkdtempSync(join(tmpdir(), 'likec4-'))
console.log('Exporteren met LikeC4 (kan even duren)...')

const run = spawnSync(
  'npx',
  ['--yes', 'likec4', 'export', 'png', '--flat', '--ignore', '-o', tmp, root],
  { cwd: root, stdio: 'inherit', shell: true },
)

if (run.status !== 0) {
  rmSync(tmp, { recursive: true, force: true })
  console.error('\nExport mislukt, de bestaande exports zijn niet aangepast.')
  process.exit(run.status ?? 1)
}

// 2. Hernoemen en de oude bestanden vervangen
mkdirSync(outDir, { recursive: true })
let ok = 0
const missing = []

for (const [id, name] of Object.entries(views)) {
  const src = join(tmp, `${id}.png`)
  if (!existsSync(src)) {
    missing.push(id)
    continue
  }
  copyFileSync(src, join(outDir, name)) // overschrijft het bestaande bestand
  console.log(`OK   ${id}  ->  exports/${name}`)
  ok++
}

rmSync(tmp, { recursive: true, force: true })

console.log(`\n${ok} van ${Object.keys(views).length} views vervangen.`)
if (missing.length) {
  console.error(`Niet gevonden (bestaande bestanden ongemoeid gelaten): ${missing.join(', ')}`)
  process.exit(1)
}
