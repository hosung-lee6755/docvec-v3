import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import './styles/tokens.css'
import './index.css'
import './styles/components.css'
import 'krds-uiux/resources/cdn/krds.min.css'
// 순서가 중요하다. KRDS 다음에 krds-theme.css를 읽어야 KRDS 색 단계와 크기 변수를
// 새 디자인 체계(마일스톤 8) 값으로 덮어쓸 수 있다.
import './styles/krds-theme.css'
// 화면 전용 CSS(styles/screens/*)가 공통 CSS 다음에 오도록 App은 CSS를 모두 읽은 뒤 가져온다.
import App from './App'
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

const router = createBrowserRouter([
  {
    path: '*',
    element: <App />,
  },
])

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Root element not found')
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  </React.StrictMode>,
)
