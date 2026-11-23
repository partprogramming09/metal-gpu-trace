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
        { text: 'Using it', link: '/guides/using-it' },
        { text: 'How it works', link: '/guides/how-it-works' },
        { text: 'Run from a clone', link: '/guides/run-from-a-clone' },
        { text: 'Data and its lifecycle', link: '/guides/data-and-lifecycle/', collapsed: true, items: [
            { text: 'Why the data is shaped this way', link: '/guides/data-and-lifecycle/why-this-shape' },
            { text: 'Files on disk', link: '/guides/data-and-lifecycle/files-on-disk' },
            { text: 'The summary, key by key', link: '/guides/data-and-lifecycle/json-keys' },
            { text: 'The project file, config.py and paths.py', link: '/guides/data-and-lifecycle/project-and-config' },
            { text: 'Retention: two mechanisms that do not mix', link: '/guides/data-and-lifecycle/retention' },
            { text: 'The cache and the lock', link: '/guides/data-and-lifecycle/cache-and-lock' },
            { text: 'From a recording to disk', link: '/guides/data-and-lifecycle/recording-to-disk' },
            { text: 'When it fails', link: '/guides/data-and-lifecycle/when-it-fails' },
            { text: 'Known limits and touching it without breaking it', link: '/guides/data-and-lifecycle/limits' },
            { text: 'Evidence E1 to E7: the runs folder', link: '/guides/data-and-lifecycle/evidence-runs' },
            { text: 'Evidence E8 to E12: the cache, the steps and the variables', link: '/guides/data-and-lifecycle/evidence-cache-and-flow' },
        ] },
        { text: 'Recording', link: '/guides/recording/', collapsed: true, items: [
            { text: 'The macOS journey', link: '/guides/recording/macos-journey' },
            { text: 'Preflight', link: '/guides/recording/preflight' },
            { text: 'Two rules: one at a time, and 30 seconds under Wine', link: '/guides/recording/rules' },
            { text: 'The test programs', link: '/guides/recording/test-programs' },
            { text: 'The Windows engine', link: '/guides/recording/windows-engine' },
            { text: 'The data files', link: '/guides/recording/data-files' },
            { text: 'When it fails, and touching it without breaking it', link: '/guides/recording/failures' },
            { text: 'Known limits', link: '/guides/recording/limits' },
            { text: 'Evidence: preflight, script, deadline, Windows engine', link: '/guides/recording/evidence' },
            { text: 'Evidence: test programs, cache and data files', link: '/guides/recording/evidence-data' },
        ] },
        { text: 'Summarizing and analyzing', link: '/guides/summarizing/', collapsed: true, items: [
            { text: 'From a trace to the summary', link: '/guides/summarizing/trace-to-summary' },
            { text: 'How each number is computed', link: '/guides/summarizing/how-numbers-are-computed' },
            { text: 'Reading and comparing', link: '/guides/summarizing/reading-and-comparing' },
            { text: 'The experiments', link: '/guides/summarizing/experiments' },
            { text: 'Noise and verdicts', link: '/guides/summarizing/noise-and-verdicts' },
            { text: 'Power and heat at both ends', link: '/guides/summarizing/power-and-heat' },
            { text: 'When it fails', link: '/guides/summarizing/when-it-fails' },
            { text: 'Changing it', link: '/guides/summarizing/changing-it' },
            { text: 'Known limits', link: '/guides/summarizing/limits' },
            { text: 'Evidence: the commands and their real output', link: '/guides/summarizing/evidence' },
        ] },
        { text: 'Reading traces', link: '/guides/reading-traces/', collapsed: true, items: [
            { text: 'Why it is shaped this way', link: '/guides/reading-traces/why-this-shape' },
            { text: 'The trace argument and what a .trace is', link: '/guides/reading-traces/trace-argument' },
            { text: 'trace_tables and trace_count', link: '/guides/reading-traces/trace-tables-count' },
            { text: 'trace_query: rows, pages and windows', link: '/guides/reading-traces/trace-query' },
            { text: 'The tables file: query a recording without its .trace', link: '/guides/reading-traces/tables-file' },
            { text: 'Exporting a .chrome-trace', link: '/guides/reading-traces/chrome-trace' },
            { text: 'The .gputrace format, as far as the code knows it', link: '/guides/reading-traces/gputrace-format' },
            { text: 'The capture tools', link: '/guides/reading-traces/capture-tools' },
            { text: 'The GPU family facts', link: '/guides/reading-traces/gpu-families' },
            { text: 'When it fails', link: '/guides/reading-traces/when-it-fails' },
            { text: 'Known limits and new findings', link: '/guides/reading-traces/limits' },
            { text: 'Touching it without breaking it', link: '/guides/reading-traces/touching-it' },
            { text: 'Evidence: the commands and their real output', link: '/guides/reading-traces/evidence' },
        ] },
        { text: 'Server and transport', link: '/guides/server-and-transport/', collapsed: true, items: [
            { text: 'Design: why the server has this shape', link: '/guides/server-and-transport/design' },
            { text: 'Configuration', link: '/guides/server-and-transport/configuration' },
            { text: 'How the server starts', link: '/guides/server-and-transport/startup' },
            { text: 'The tool registry', link: '/guides/server-and-transport/registry' },
            { text: 'The worker', link: '/guides/server-and-transport/worker' },
            { text: 'The two eras, as a reference', link: '/guides/server-and-transport/eras' },
            { text: 'HTTP in detail', link: '/guides/server-and-transport/http' },
            { text: 'Logs', link: '/guides/server-and-transport/logs' },
            { text: 'When it fails', link: '/guides/server-and-transport/failures' },
            { text: 'Known limits', link: '/guides/server-and-transport/limits' },
            { text: 'Touching it without breaking it', link: '/guides/server-and-transport/touching' },
            { text: 'Evidence: the commands and their real output', link: '/guides/server-and-transport/evidence' },
        ] },
      ] }],
    },
    search: { provider: 'local' },
  },
})
