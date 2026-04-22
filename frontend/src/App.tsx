import { Routes, Route, NavLink, Navigate } from "react-router-dom"
import UploadPage from "@/pages/UploadPage"
import SessionDetailPage from "@/pages/SessionDetailPage"
import OneRmPage from "@/pages/OneRmPage"
import { Activity } from "lucide-react"

function Nav() {
  const linkCls = ({ isActive }: { isActive: boolean }) =>
    `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
      isActive
        ? "bg-primary text-primary-foreground"
        : "text-muted-foreground hover:bg-muted hover:text-foreground"
    }`
  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
        <div className="flex items-center gap-2 font-semibold">
          <Activity className="h-5 w-5 text-primary" />
          IMU Lab
        </div>
        <nav className="flex items-center gap-1">
          <NavLink to="/" end className={linkCls}>
            Sessions
          </NavLink>
          <NavLink to="/one-rm" className={linkCls}>
            1RM Consensus
          </NavLink>
        </nav>
      </div>
    </header>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <Nav />
      <main className="mx-auto max-w-7xl px-6 py-8">
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/sessions/:id" element={<SessionDetailPage />} />
          <Route path="/one-rm" element={<OneRmPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
