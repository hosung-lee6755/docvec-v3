import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import 'krds-uiux/resources/cdn/krds.min.css'
// krds.min.css declares `body, html { color: ... }` at the same specificity as our
// own `body { color: var(--color-text) }`, and KRDS loads second so it wins the tie —
// meaning any text that doesn't set its own color inherits KRDS's dark base text color.
// This is invisible on our dark-background elements (Dashboard cards, dark-theme auth
// pages). Rather than reordering imports (which would also flip KRDS's own white page
// background back to dark on the light-themed pages), every element sitting on a dark
// background must set its text color explicitly instead of relying on inheritance.
// krds.min.js is a vanilla-DOM enhancement script (custom select/modal widgets) built
// for static server-rendered pages. It corrupts layout when React mounts/unmounts these
// elements client-side (observed: duplicated <select> nodes with broken 1849px bounding
// boxes). We don't use any of its interactive behavior — every KRDS component here is
// React-state-controlled — so only the stylesheet is needed.

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60,
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  </React.StrictMode>,
)
