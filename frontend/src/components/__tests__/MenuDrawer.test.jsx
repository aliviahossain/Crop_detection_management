import { expect, test } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { LANGUAGES, LangContext } from '../../lib/i18n.js'
import MenuDrawer, { MENU_GROUPS } from '../MenuDrawer.jsx'

const render = (lang, open) =>
  renderToStaticMarkup(
    <MemoryRouter initialEntries={['/check']}>
      <LangContext.Provider value={{ lang, setLang: () => {} }}>
        <MenuDrawer open={open} onClose={() => {}} />
      </LangContext.Provider>
    </MemoryRouter>,
  )

test('renders nothing while closed, so the scrim never traps taps', () => {
  expect(render('mr', false)).toBe('')
})

test('every feature and language is reachable from the drawer', () => {
  const html = render('mr', true)
  for (const group of MENU_GROUPS) {
    for (const item of group.items) expect(html).toContain(`href="${item.to}"`)
  }
  for (const { label } of LANGUAGES) expect(html).toContain(label)
})

test('the current page is marked, so the farmer knows where they are', () => {
  expect(render('en', true)).toContain('menu-item active')
})

test('each entry carries a description in every language', () => {
  // A key with no translation falls back to the key itself, which would ship a
  // raw 'nav.scan.desc' to a farmer. Catch that here rather than in the field.
  for (const { code } of LANGUAGES) {
    const html = render(code, true)
    for (const group of MENU_GROUPS) {
      for (const item of group.items) expect(html).not.toContain(`${item.key}.desc`)
    }
  }
})
