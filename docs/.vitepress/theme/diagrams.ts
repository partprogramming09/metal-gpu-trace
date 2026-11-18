// Chrome's translator skips text inside <svg>, so each <text> becomes an HTML <span> laid over the shapes.

function convert(box: Element) {
  const svg = box.querySelector('svg')
  if (!svg || box.getAttribute('data-ready')) return
  const vb = svg.viewBox.baseVal
  if (!vb.width) return
  const texts = Array.from(svg.querySelectorAll('text'))
  const boxes = Array.from(svg.querySelectorAll('rect')).map((r) => r.getBBox()).filter((r) => r.width > 40 && r.width < vb.width * 0.9 && r.height > 20)
  const bboxes = texts.map((t) => t.getBBox())
  // Lines of one paragraph (same x, size and colour, one line apart) become one label, so the translator sees the whole sentence.
  const styles = texts.map((t) => getComputedStyle(t))
  const groups: number[][] = []
  texts.forEach((_, i) => {
    const g = groups[groups.length - 1]
    const j = g && g[g.length - 1]
    const same = j !== undefined && j === i - 1 && styles[i].textAnchor === styles[j].textAnchor && styles[i].fontSize === styles[j].fontSize &&
      styles[i].fontWeight === styles[j].fontWeight && styles[i].fill === styles[j].fill && styles[i].fontFamily === styles[j].fontFamily &&
      Math.abs(bboxes[i].x - bboxes[j].x) < 1.5 + Math.abs(bboxes[i].width - bboxes[j].width) / 2 && bboxes[i].y - bboxes[j].y > bboxes[j].height * 0.8 && bboxes[i].y - bboxes[j].y < bboxes[j].height * 1.7
    if (same) g.push(i)
    else groups.push([i])
  })
  const labels = groups.map((g) => {
    const i = g[0]
    const t = texts[i]
    const b = bboxes[i]
    const cs = styles[i]
    const mono = /mono|courier/i.test(cs.fontFamily)
    const anchor = cs.textAnchor
    const x = anchor === 'middle' ? b.x + b.width / 2 : anchor === 'end' ? b.x + b.width : b.x
    const el = document.createElement('span')
    el.className = 'dg-label'
    el.textContent = g.map((k) => texts[k].textContent).join(' ')
    if (mono) el.setAttribute('translate', 'no') // commands and names are not translated
    // A label inside a box wraps at the box edge: translated text is longer and must not spill out of it.
    const cx = b.x + b.width / 2
    const cy = b.y + b.height / 2
    const box = boxes.filter((r) => cx > r.x && cx < r.x + r.width && cy > r.y && cy < r.y + r.height).sort((m, n) => m.width - n.width)[0]
    // With no box around it, the diagram's own edges are the limit.
    const area = box ?? { x: 0, y: 0, width: vb.width, height: vb.height }
    // The label wraps inside its box (or the diagram) and never reaches the neighbours on its row.
    const row = bboxes.filter((o, j) => !g.includes(j) && o.y < b.y + b.height && o.y + o.height > b.y)
    const left = Math.max(area.x + 4, ...row.filter((o) => o.x + o.width <= b.x + 1).map((o) => o.x + o.width + 4))
    const right = Math.min(area.x + area.width - 4, ...row.filter((o) => o.x >= b.x + b.width - 1).map((o) => o.x - 4))
    // Centred neighbours share the gap between them: each one gets half of it.
    const half = (side: typeof row, edge: number) => Math.min(Math.abs(edge - x), ...side.map((o) => Math.abs(o.x + o.width / 2 - x) / 2))
    const w = anchor === 'middle' ? 2 * Math.min(half(row.filter((o) => o.x + o.width <= b.x + 1), left), half(row.filter((o) => o.x >= b.x + b.width - 1), right)) - 8 : anchor === 'end' ? x - left - 4 : right - x - 4
    const wrap = `width:${(Math.max(w, 10) / vb.width) * 100}%;white-space:normal;text-align:${anchor === 'middle' ? 'center' : anchor === 'end' ? 'right' : 'left'};`
    el.dataset.bottom = String((area.y + area.height - 3) / vb.height) // fraction of the diagram height
    el.style.cssText = wrap +
      `left:${(x / vb.width) * 100}%;top:${(b.y / vb.height) * 100}%;` +
      `transform:translateX(${anchor === 'middle' ? '-50%' : anchor === 'end' ? '-100%' : '0'});` +
      `font-size:${(parseFloat(cs.fontSize) / vb.width) * 93}cqw;font-weight:${cs.fontWeight};` +
      `color:${cs.fill};letter-spacing:${cs.letterSpacing};` +
      (mono ? 'font-family:var(--vp-font-family-mono);' : '') +
      (cs.textTransform === 'uppercase' ? 'text-transform:uppercase;' : '')
    return { t: g.map((k) => texts[k]), el }
  })
  labels.forEach(({ t, el }) => {
    box.appendChild(el)
    t.forEach((x) => x.remove())
  })
  const fit = () => {
    const h = box.getBoundingClientRect()
    box.querySelectorAll<HTMLElement>('.dg-label[data-bottom]').forEach((l) => {
      const limit = h.top + parseFloat(l.dataset.bottom!) * h.height
      const base = (l.dataset.size ??= String(parseFloat(l.style.fontSize)))
      l.style.fontSize = `${base}cqw`
      for (let k = 0; k < 8 && l.getBoundingClientRect().bottom > limit; k++) l.style.fontSize = `${parseFloat(l.style.fontSize) * 0.92}cqw`
    })
  }
  // The translator rewrites the labels: fit again so the longer text stays inside its box.
  let pending = 0
  new MutationObserver(() => { clearTimeout(pending); pending = window.setTimeout(fit, 60) }).observe(box, { subtree: true, childList: true, characterData: true })
  svg.setAttribute('aria-hidden', 'true') // the figure's aria-label describes it; the labels below stay readable
  box.setAttribute('data-ready', '1')
  fit()
}

export function convertDiagrams() {
  document.querySelectorAll('.vp-doc .dg-box').forEach(convert)
}

// Click on a diagram: full width over the page and back.
export function toggleDiagram(ev: Event) {
  const fig = (ev.target as Element).closest?.('.dg')
  if (fig) fig.classList.toggle('dg-open')
}
