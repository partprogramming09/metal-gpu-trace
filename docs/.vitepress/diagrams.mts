import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')

// For `![alt](img/x.png)` it inlines the SVG of the sibling `img/x.html`, so the browser's translator can reach the labels
// (it skips text inside <svg>: theme/diagrams.ts moves them to HTML). The .png stays for GitHub and the README.
export function inlineDiagram(mdFile: string | undefined, src: string, alt: string): string | null {
  if (!mdFile || !src.endsWith('.png') || /^(https?:)?\/\//.test(src)) return null
  const html = resolve(dirname(mdFile), src.slice(0, -4) + '.html')
  if (!existsSync(html)) return null
  const svg = readFileSync(html, 'utf-8').match(/<svg[\s\S]*<\/svg>/)
  if (!svg) return null
  return `<figure class="dg" role="group" aria-label="${esc(alt)}"><div class="dg-box">${svg[0]}</div><figcaption class="dg-alt">${esc(alt)}</figcaption></figure>`
}
