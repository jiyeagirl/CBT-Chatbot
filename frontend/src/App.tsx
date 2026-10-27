import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { isOnboarded } from './lib/preferences'
import { Chat } from './pages/Chat'
import { Home } from './pages/Home'
import { Onboarding } from './pages/Onboarding'
import { RecordDetail } from './pages/RecordDetail'
import { Records } from './pages/Records'

function RequireOnboarding({ children }: { children: React.ReactNode }) {
  return isOnboarded() ? children : <Navigate to="/onboarding" replace />
}

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route
          path="/"
          element={
            <RequireOnboarding>
              <Home />
            </RequireOnboarding>
          }
        />
        <Route
          path="/chat"
          element={
            <RequireOnboarding>
              <Chat />
            </RequireOnboarding>
          }
        />
        <Route
          path="/records"
          element={
            <RequireOnboarding>
              <Records />
            </RequireOnboarding>
          }
        />
        <Route
          path="/records/:id"
          element={
            <RequireOnboarding>
              <RecordDetail />
            </RequireOnboarding>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}
