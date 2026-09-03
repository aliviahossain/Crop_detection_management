import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from 'vitest'
import { LANGUAGES, translationCoverage } from '../i18n.js'

const SRC = join(import.meta.dirname, '..', '..')

function sourceFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === '__tests__' ? [] : sourceFiles(path)
    return /\.jsx?$/.test(name) ? [path] : []
  })
}

test('no em or en dash appears anywhere in the UI source', () => {
  const offenders = sourceFiles(SRC)
    .filter((path) => /[—–]/.test(readFileSync(path, 'utf8')))
    .map((path) => path.slice(SRC.length + 1))
  expect(offenders).toEqual([])
})

test('every string is translated into every language', () => {
  const coverage = translationCoverage()
  for (const { code } of LANGUAGES) {
    expect(coverage[code].have).toBe(coverage[code].total)
  }
})
