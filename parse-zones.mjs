#!/usr/bin/env node
// parse-zones.mjs
// Usage: node parse-zones.mjs [-o outdir] [input.md] [output.json]
//   -o outdir  - write output to outdir/<input-basename>.json
//   input.md   - liteparse JSON output (default: output.md)
//   output     - destination JSON file (default: same name as input, .json)
//
// Extracts the KEY ZONES table from a liteparse-parsed trader worksheet PDF
// and writes it in the zones.json schema:
//   { "key-zones": { "resistance": [...], "support": [...] } }

import { readFileSync, writeFileSync } from 'fs';
import { resolve, join, basename } from 'path';

const args = process.argv.slice(2);
let outputDir = null;
const positional = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '-o' && i + 1 < args.length) {
    outputDir = args[++i];
  } else {
    positional.push(args[i]);
  }
}

const INPUT_FILE = positional[0] ?? 'output.md';
const OUTPUT_FILE = outputDir
  ? join(outputDir, basename(INPUT_FILE).replace(/\.[^.]+$/, '.json'))
  : (positional[1] ?? INPUT_FILE.replace(/\.[^.]+$/, '.json'));

// ── Column x-boundaries (points) ────────────────────────────────────────────
const ZONE_COL_MAX  = 150;   // zone range column:  x < 150
const BIAS_COL_MIN  = 150;   // bias column:        150 <= x < 300
const BIAS_COL_MAX  = 300;
const NOTES_COL_MIN = 300;   // notes column:       x >= 300

// Max cumulative-Y distance to assign a bias/notes cell to a zone row.
// Rows are ~14pt apart; notes sometimes split ±6pt above/below.
// Gap to the next non-zone section (10-Day Range Analysis) is ~34pt, so 25 is safe.
const MAX_ASSIGN_DIST = 25;

// Section labels found in the zone column
const SECTION_LABELS = new Set(['Resistance', 'Support']);

// Matches a zone range: "7290-7300", "7246", "7179.50-7189.50", "7105.50"
const PRICE_RANGE_RE = /^\d+(\.\d+)?(-\d+(\.\d+)?)?$/;

// Table border characters that OCR sometimes picks up as text items
const TABLE_BORDER_RE = /^[|[\]│┤├┼└┘┐┌─+\-=\s]+$/;
const clean = i => !TABLE_BORDER_RE.test(i.text);

function parseZoneRange(text) {
  const t = text.trim();
  if (!PRICE_RANGE_RE.test(t)) return null;
  const dash = t.lastIndexOf('-');
  if (dash <= 0) {
    const v = parseFloat(t);
    return isNaN(v) ? null : { lo: v, hi: v };
  }
  const lo = parseFloat(t.slice(0, dash));
  const hi = parseFloat(t.slice(dash + 1));
  return (isNaN(lo) || isNaN(hi)) ? null : { lo, hi };
}

// Directional Bias label prefixes → output keys
const BIAS_LABEL_KEYS = [
  { prefix: 'Short-term',    key: 'short-term'     },
  { prefix: 'Intermediate',  key: 'intermediate'   },
  { prefix: 'Bigger Picture',key: 'bigger-picture' },
];

// ── Load & flatten ───────────────────────────────────────────────────────────
const raw  = readFileSync(resolve(INPUT_FILE), 'utf8');
const data = JSON.parse(raw);

const pageHeight = data.pages[0]?.height ?? 792;

// cumY = (page_index * pageHeight) + y  →  continuous vertical coordinate
const allItems = data.pages.flatMap((page, pi) =>
  page.textItems.map(item => ({ ...item, cumY: pi * pageHeight + item.y }))
);
allItems.sort((a, b) => a.cumY - b.cumY || a.x - b.x);

// ── Locate section anchors ───────────────────────────────────────────────────
const keyZonesItem = allItems.find(item => item.text.trim() === 'KEY ZONES');
if (!keyZonesItem) throw new Error('KEY ZONES heading not found');

// cumY of every "10-Day Range Analysis" heading (can appear on multiple pages)
const rangeAnalysisCumYs = allItems
  .filter(i => i.text.trim() === '10-Day Range Analysis')
  .map(i => i.cumY)
  .sort((a, b) => a - b);

const after = allItems.filter(item => item.cumY > keyZonesItem.cumY);

// ── Extract Directional Bias ─────────────────────────────────────────────────
// In the original textItems order (document reading order) the 3 bias rows
// appear contiguously immediately after the "Directional Bias" heading entry,
// before the Economic Reports section.  Collect items into y-rows and stop
// once we have 3, so unrelated items never contaminate the result.
const page1Items = data.pages[0].textItems;
const dbIdx = page1Items.findIndex(i => i.text.trim() === 'Directional Bias');
if (dbIdx === -1) throw new Error('Directional Bias heading not found');

const bias = {};
const dbRows = [];
let rowY = null, rowItems = [];

for (let i = dbIdx + 1; i < page1Items.length && dbRows.length < 3; i++) {
  const item = page1Items[i];
  if (!clean(item)) continue;
  if (rowY === null || Math.abs(item.y - rowY) < 3) {
    if (rowY === null) rowY = item.y;
    rowItems.push(item);
  } else {
    dbRows.push(rowItems);
    rowY = item.y;
    rowItems = [item];
  }
}
if (rowItems.length > 0 && dbRows.length < 3) dbRows.push(rowItems);

for (const row of dbRows) {
  const text = row.sort((a, b) => a.x - b.x).map(i => i.text.trim()).join(' ').trim();
  for (const { prefix, key } of BIAS_LABEL_KEYS) {
    if (text.startsWith(prefix)) {
      bias[key] = text.slice(prefix.length).trim();
      break;
    }
  }
}

// ── Split into columns (exclude OCR table-border artifacts) ──────────────────
const zoneCol  = after.filter(i => i.x < ZONE_COL_MAX);
const biasCol  = after.filter(i => i.x >= BIAS_COL_MIN && i.x < BIAS_COL_MAX && clean(i));
const notesCol = after.filter(i => i.x >= NOTES_COL_MIN && clean(i));

// ── Identify section headers vs zone data rows ───────────────────────────────
const sectionHeaders = zoneCol.filter(i => SECTION_LABELS.has(i.text.trim()));
const zoneRows       = zoneCol.filter(i =>
  !SECTION_LABELS.has(i.text.trim()) && parseZoneRange(i.text) !== null
);

if (zoneRows.length === 0) throw new Error('No zone rows found after KEY ZONES');

// cumY values of section-header rows (to exclude column-header labels
// like "Effect on Intraday Bias" / "Notes" that share the same row)
const headerCumYSet = new Set(sectionHeaders.map(h => Math.round(h.cumY * 10)));
function isHeaderRow(item) {
  return headerCumYSet.has(Math.round(item.cumY * 10));
}

// ── Assign bias / notes cells to zone rows via nearest-cumY (Voronoi) ────────
function buildAssignments(colItems) {
  const map = new Map(zoneRows.map(zr => [zr, []]));
  for (const item of colItems) {
    if (isHeaderRow(item)) continue;
    let nearest = null, minDist = MAX_ASSIGN_DIST + 1;
    for (const zr of zoneRows) {
      const d = Math.abs(zr.cumY - item.cumY);
      if (d < minDist) { minDist = d; nearest = zr; }
    }
    if (nearest) map.get(nearest).push(item);
  }
  return map;
}

const biasMap  = buildAssignments(biasCol);
const notesMap = buildAssignments(notesCol);

// ── Determine section (resistance / support) for each zone row ───────────────
const sortedHeaders = sectionHeaders.slice().sort((a, b) => a.cumY - b.cumY);
function getSectionFor(item) {
  let section = null;
  for (const h of sortedHeaders) {
    if (h.cumY <= item.cumY) section = h.text.toLowerCase();
    else break;
  }
  return section;
}

// ── Build output ─────────────────────────────────────────────────────────────
const resistance = [];
const support    = [];

let prevZoneCumY = -Infinity;  // cumY of the last accepted zone row
let lastLo       = null;       // zone_lo of the last accepted zone
let inSkipRegion = false;      // true while skipping 10-Day Range Analysis junk rows

for (const zr of zoneRows) {
  const section = getSectionFor(zr);
  if (!section) continue;

  const range = parseZoneRange(zr.text);
  if (!range) continue;

  // If a 10-Day Range Analysis heading appeared between the last good zone and
  // this one, and zone_lo drops by more than 50, enter skip mode.
  if (!inSkipRegion) {
    const triggered = rangeAnalysisCumYs.some(ry => ry > prevZoneCumY && ry < zr.cumY);
    if (triggered && lastLo !== null && (lastLo - range.lo) > 50) {
      inSkipRegion = true;
    }
  }

  // In skip mode: resume only when zone_lo is back within 50 of the last good value.
  if (inSkipRegion) {
    if (lastLo !== null && Math.abs(range.lo - lastLo) <= 50) {
      inSkipRegion = false;
    } else {
      continue;
    }
  }

  const biasItems  = (biasMap.get(zr)  ?? []).sort((a, b) => a.cumY - b.cumY || a.x - b.x);
  const notesItems = (notesMap.get(zr) ?? []).sort((a, b) => a.cumY - b.cumY || a.x - b.x);

  const bias_effect = biasItems
    .map(i => i.text.trim()).join(' ')
    .replace(/\s+/g, ' ').replace(/ ,/g, ',').trim();

  const notes = notesItems
    .map(i => i.text.trim()).join(' ')
    .replace(/\s+/g, ' ').replace(/ ,/g, ',').trim();

  const entry = { zone_lo: range.lo, zone_hi: range.hi, bias_effect, notes };
  if (section === 'resistance') resistance.push(entry);
  else                          support.push(entry);

  lastLo       = range.lo;
  prevZoneCumY = zr.cumY;
}

const dateKey = basename(INPUT_FILE).match(/^(\d{8})/)?.[1] ?? 'unknown';
const result = { [dateKey]: { bias, 'key-zones': { resistance, support } } };
writeFileSync(resolve(OUTPUT_FILE), JSON.stringify(result, null, 2));

console.log(`✓ bias: ${Object.entries(bias).map(([k,v]) => `${k}=${v}`).join(', ')}`);
console.log(`✓ ${resistance.length} resistance zones, ${support.length} support zones → ${OUTPUT_FILE}`);
