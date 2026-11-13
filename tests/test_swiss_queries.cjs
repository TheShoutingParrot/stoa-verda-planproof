// Run with: node --test tests/test_swiss_queries.cjs
'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {spawnSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const sourceSheet = JSON.parse(fs.readFileSync(path.join(root, 'public/data/swiss-floor.json'), 'utf8'));

function ask(sheet, questions) {
  const child = spawnSync(process.execPath, ['scripts/benchmark_swiss.cjs', 'public/app.js'], {
    cwd: root, input: JSON.stringify([{sheet, questions}]), encoding: 'utf8'
  });
  assert.equal(child.status, 0, child.stderr);
  return JSON.parse(child.stdout);
}

test('feature and unit counts supply distinct evidence identifiers', () => {
  const [doors, apartments, noShowers, room] = ask(sourceSheet, [
    'How many doors (interior doors and entrance doors together) are drawn on this floor plan?',
    'How many apartments (residential units) are shown on this floor plan?',
    'How many showers are drawn on this floor plan?',
    "What is the net floor area of room 5.11 ('Stanza') in m²?"
  ]);
  assert.deepEqual(doors.scope, {kind:'object_count', target:'doors'});
  assert.equal(doors.value, 21);
  assert.equal(new Set(doors.evidence).size, 21);
  assert.deepEqual(apartments.evidence, ['unit:A', 'unit:B']);
  assert.equal(apartments.value, 2);
  assert.equal(noShowers.value, 0);
  assert.deepEqual(noShowers.evidence, []);
  assert.deepEqual(room.evidence, ['5.11']);
  assert.equal(room.value, 13.62);
});

test('unresolved apartment and floor memberships produce unavailable, never a partial area', () => {
  const sheet = structuredClone(sourceSheet);
  sheet.floorComplete = false;
  sheet.apartmentCountComplete = false;
  sheet.apartments[0].complete = false;
  const questions = [
    'How many apartments are on this floor?',
    'What is the net indoor area of apartment A?',
    'What is the net area of all numbered indoor rooms?'
  ];
  for (const r of ask(sheet, questions)) {
    assert.equal(r.value, null);
    assert.deepEqual(r.evidence, []);
  }
});

test('mixed takeoffs and unhandled units do not silently return whole-room aggregates', () => {
  const prompts = [
    'How many doors are in Stanza rooms?',
    'Please count doors in kitchens',
    'What is the total area of all numbered rooms?',
    'Can you tell me how many doors the kitchen contains?',
    'I need the area of Stanza in square feet',
    "What is the area of windows in rooms labelled 'Stanza'?",
    'How many doors does the kitchen contain?',
    "How many rooms labelled 'Stanza' have windows?",
    "What is the area of rooms labelled 'Stanza' in square feet?",
    "What is the gross area of rooms labelled 'Stanza'?",
    "How many rooms labelled 'Stanza' are there on a different floor?"
  ];
  const results = ask(sourceSheet, prompts);
  for (const [index, r] of results.entries()) {
    assert.equal(r.value, null, prompts[index] + ' silently produced ' + r.display);
    assert.deepEqual(r.evidence, []);
  }
});
