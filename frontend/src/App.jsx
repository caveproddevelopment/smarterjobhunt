import { Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'
import JobListings from './pages/JobListings'
import Login from './pages/Login'
import { AuthProvider } from './lib/auth'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/dashboard" element={<JobListings />} />
        <Route path="/login" element={<Login />} />
      </Routes>
    </AuthProvider>
  )
}
