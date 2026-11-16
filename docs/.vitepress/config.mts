import { defineConfig } from 'vitepress'

// Cambia estos cuatro valores al copiar la plantilla.
const titulo = 'metal-gpu-trace'
const descripcion = 'An MCP server that records Wine or macOS programs with Instruments\' Metal System Trace on Apple silicon and reads the recordings back.'
const repo = 'https://github.com/partprogramming09/metal-gpu-trace'

export default defineConfig({
  lang: 'en',
  title: titulo,
  description: descripcion,
  cleanUrls: true,
  // Plans and internal notes are never published; templates are copied, not published; README.md is the index for people browsing the repository
  srcExclude: ['README.md', 'plans/**', 'estado.md', 'research/**'],
  lastUpdated: true,
  head: [
    ['meta', { property: 'og:title', content: titulo }],
    ['meta', { property: 'og:description', content: descripcion }],
  ],
  themeConfig: {
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Guides', link: '/guides/' },
      { text: 'Contributing', link: `${repo}/blob/main/CONTRIBUTING.md` },
    ],
    sidebar: {
      '/guides/': [{ text: 'Guides', items: [
        { text: 'What this is about', link: '/guides/' },
        { text: 'Data and its lifecycle', link: '/guides/data-and-lifecycle' },
      ] }],
      '/es/guides/': [{ text: 'Guías (español)', items: [
        { text: 'Datos y su ciclo de vida', link: '/es/guides/datos-y-su-ciclo-de-vida' },
      ] }],
    },
    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: 'Buscar', buttonAriaLabel: 'Buscar' },
          modal: {
            displayDetails: 'Ver detalles',
            resetButtonTitle: 'Borrar búsqueda',
            noResultsText: 'Sin resultados para',
            footer: { selectText: 'seleccionar', navigateText: 'moverse', closeText: 'cerrar' },
          },
        },
      },
    },
    darkModeSwitchLabel: 'Apariencia',
    sidebarMenuLabel: 'Menú',
    returnToTopLabel: 'Volver arriba',
    outline: { label: 'En esta página' },
    docFooter: { prev: 'Anterior', next: 'Siguiente' },
    lastUpdated: { text: 'Actualizado' },
  },
})
