import DefaultTheme from 'vitepress/theme'
import { onMounted, watch, nextTick } from 'vue'
import { useRoute } from 'vitepress'
import mediumZoom from 'medium-zoom'
import './custom.css'
import { convertDiagrams, toggleDiagram } from './diagrams'

export default {
  extends: DefaultTheme,
  // Clic en un diagrama para verlo grande. Solo corre en el navegador (en el build no hay `window`).
  setup() {
    const route = useRoute()
    const zoom = () => mediumZoom('.vp-doc img', { background: 'var(--vp-c-bg)' })
    const diagrams = () => { zoom(); convertDiagrams() }
    onMounted(() => { diagrams(); document.addEventListener('click', toggleDiagram) })
    watch(() => route.path, () => nextTick(diagrams))
  },
}
