import { Navigate, Route, Routes } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import LeadDiscovery from './pages/LeadDiscovery'
import LeadResearch from './pages/LeadResearch'
import LeadScoring from './pages/LeadScoring'
import Campaigns from './pages/Campaigns'
import EmailWriter from './pages/EmailWriter'
import VideoStudio from './pages/VideoStudio'
import FollowUps from './pages/FollowUps'
import Inbox from './pages/Inbox'
import CRM from './pages/CRM'
import Analytics from './pages/Analytics'
import Integrations from './pages/Integrations'
import Settings from './pages/Settings'
import Assistant from './pages/Assistant'

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
        <Route index element={<Dashboard />} />
        {PAGES.map(([path, Page]) => (
          <Route key={path} path={path} element={<Page />} />
        ))}
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
