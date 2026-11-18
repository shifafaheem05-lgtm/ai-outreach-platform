import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import Login from './pages/Login'
const Dashboard = lazy(() => import('./pages/Dashboard'))
const LeadDiscovery = lazy(() => import('./pages/LeadDiscovery'))
const LeadResearch = lazy(() => import('./pages/LeadResearch'))
const LeadScoring = lazy(() => import('./pages/LeadScoring'))
const Campaigns = lazy(() => import('./pages/Campaigns'))
const EmailWriter = lazy(() => import('./pages/EmailWriter'))
const VideoStudio = lazy(() => import('./pages/VideoStudio'))
const FollowUps = lazy(() => import('./pages/FollowUps'))
const Inbox = lazy(() => import('./pages/Inbox'))
const CRM = lazy(() => import('./pages/CRM'))
const Analytics = lazy(() => import('./pages/Analytics'))
const Integrations = lazy(() => import('./pages/Integrations'))
const Settings = lazy(() => import('./pages/Settings'))
const Assistant = lazy(() => import('./pages/Assistant'))

const PAGES = [
  ['/lead-discovery', LeadDiscovery],
  ['/lead-research', LeadResearch],
  ['/lead-scoring', LeadScoring],
  ['/campaigns', Campaigns],
  ['/email-writer', EmailWriter],
  ['/video-studio', VideoStudio],
  ['/follow-ups', FollowUps],
  ['/inbox', Inbox],
  ['/crm', CRM],
  ['/analytics', Analytics],
  ['/integrations', Integrations],
  ['/settings', Settings],
  ['/assistant', Assistant],
]

function Protected({ children }) {
  const { user, loading } = useAuth()
  if (loading)
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
      </div>
    )
  return user ? children : <Navigate to="/login" replace />
}

const PageSpinner = () => (
  <div className="flex justify-center py-24"><Loader2 className="h-6 w-6 animate-spin text-brand-600" /></div>
)

/** Wraps every page: lazy-load fallback + error boundary that resets on navigation. */
function Page({ children }) {
  const { pathname } = useLocation()
  return (
    <ErrorBoundary resetKey={pathname}>
      <Suspense fallback={<PageSpinner />}>{children}</Suspense>
    </ErrorBoundary>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        <Route index element={<Page><Dashboard /></Page>} />
        {PAGES.map(([path, Component]) => (
          <Route key={path} path={path} element={<Page><Component /></Page>} />
        ))}
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
