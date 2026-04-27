#!/usr/bin/env node
// parse-zones.mjs
// Usage: node parse-zones.mjs [input.md] [output.json]
//   input.md  - liteparse JSON output (default: output.md)
//   output    - destination JSON file (default: zones.json)
//
// Extracts the KEY ZONES table from a liteparse-parsed trader worksheet PDF
// and writes it in the zones.json schema:
//   { "key-zones": { "resistance": [...], "support": [...] } }

import { readFileSync, writeFileSync } from 'fs';
import { resolve } from 'path';

const INPUT_FILE  = process.argv[2] ?? 'output.md';
const OUTPUT_FILE = process.argv[3] ?? INPUT_FILE.replace(/\.[^.]+$/, '.json');

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

// ── Load & flatten ───────────────────────────────────────────────────────────
const raw  = readFileSync(resolve(INPUT_FILE), 'utf8');
const data = JSON.parse(raw);

const pageHeight = data.pages[0]?.height ?? 792;

// cumY = (page_index * pageHeight) + y  →  continuous vertical coordinate
const allItems = data.pages.flatMap((page, pi) =>
  page.textItems.map(item => ({ ...item, cumY: pi * pageHeight + item.y }))
);
allItems.sort((a, b) => a.cumY - b.cumY || a.x - b.x);

// ── Locate KEY ZONES section ─────────────────────────────────────────────────
const keyZonesItem = allItems.find(item => item.text.trim() === 'KEY ZONES');
if (!keyZonesItem) throw new Error('KEY ZONES heading not found');

const after = allItems.filter(item => item.cumY > keyZonesItem.cumY);

// ── Split into columns (exclude OCR table-border artifacts) ──────────────────
const clean = i => !TABLE_BORDER_RE.test(i.text);
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

for (const zr of zoneRows) {
  const section = getSectionFor(zr);
  if (!section) continue;

  const range = parseZoneRange(zr.text);
  if (!range) continue;

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
}

const result = { 'key-zones': { resistance, support } };
writeFileSync(resolve(OUTPUT_FILE), JSON.stringify(result, null, 2));

console.log(`✓ ${resistance.length} resistance zones, ${support.length} support zones → ${OUTPUT_FILE}`);
