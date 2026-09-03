import { Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'
import JobListings from './pages/JobListings'
import Login from './pages/Login'
import ResetPassword from './pages/ResetPassword'
import Profile from './pages/Profile'
import WhatIsThis from './pages/WhatIsThis'
import FAQ from './pages/FAQ'
import Pricing from './pages/Pricing'
import AboutUs from './pages/AboutUs'
import TermsOfService from './pages/TermsOfService'
import PrivacyPolicy from './pages/PrivacyPolicy'
import { AuthProvider } from './lib/auth'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/dashboard" element={<JobListings />} />
        <Route path="/login" element={<Login />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/what-is-this" element={<WhatIsThis />} />
        <Route path="/faq" element={<FAQ />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/about" element={<AboutUs />} />
        <Route path="/terms" element={<TermsOfService />} />
        <Route path="/privacy" element={<PrivacyPolicy />} />
      </Routes>
    </AuthProvider>
  )
}