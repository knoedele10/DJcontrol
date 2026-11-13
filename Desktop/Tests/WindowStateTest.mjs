import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { loadWindowState, saveWindowState } from '../dist/WindowState.js'

const displays = [{ workArea: { x: 0, y: 0, width: 1920, height: 1040 } }]

test('loadWindowState returns defaults when file is missing or malformed', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kgdash-win-'))
  try {
    const missing = path.join(dir, 'windowstate.json')
    assert.deepEqual(loadWindowState(missing, displays), {
      width: 1440,
      height: 900,
      maximized: false,
    })

    fs.writeFileSync(missing, '{bad json', 'utf8')
    assert.deepEqual(loadWindowState(missing, displays), {
      width: 1440,
      height: 900,
      maximized: false,
    })
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('saveWindowState persists clamped bounds and restores visible position', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kgdash-win-'))
  try {
    const file = path.join(dir, 'nested', 'windowstate.json')
    saveWindowState(file, { width: 800, height: 500, x: 120.4, y: 80.6 }, true)
    assert.deepEqual(loadWindowState(file, displays), {
      width: 1024,
      height: 680,
      x: 120,
      y: 81,
      maximized: true,
    })
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('loadWindowState drops off-screen coordinates when external display is disconnected', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kgdash-win-'))
  try {
    const file = path.join(dir, 'windowstate.json')
    saveWindowState(file, { width: 1280, height: 760, x: 2500, y: 100 }, false)
    assert.deepEqual(loadWindowState(file, displays), {
      width: 1280,
      height: 760,
      maximized: false,
    })
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})
