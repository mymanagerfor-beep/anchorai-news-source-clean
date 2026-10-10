import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import AppLayout from "@/components/AppLayout";
import Landing from "@/pages/Landing";
import { Login, Signup, ForgotPassword, ResetPassword, VerifyEmail } from "@/pages/Auth";
import Dashboard from "@/pages/Dashboard";
import Anchors from "@/pages/Anchors";
import Channels from "@/pages/Channels";
import Creator from "@/pages/Creator";
import Jobs from "@/pages/Jobs";
import Library from "@/pages/Library";
import Billing from "@/pages/Billing";
import Account from "@/pages/Account";
import Admin from "@/pages/Admin";

function Protected({ children, admin }) {
  const { user } = useAuth();
  if (user === null) return <div className="flex min-h-screen items-center justify-center text-slate-400" data-testid="auth-loading">Loading studio…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (admin && user.role !== "admin") return <Navigate to="/app" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/verify-email" element={<VerifyEmail />} />
          <Route path="/app" element={<Protected><AppLayout /></Protected>}>
            <Route index element={<Dashboard />} />
            <Route path="new" element={<Creator />} />
            <Route path="new/:projectId" element={<Creator />} />
            <Route path="jobs" element={<Jobs />} />
            <Route path="library" element={<Library />} />
            <Route path="anchors" element={<Anchors />} />
            <Route path="channels" element={<Channels />} />
            <Route path="billing" element={<Billing />} />
            <Route path="account" element={<Account />} />
            <Route path="admin" element={<Protected admin><Admin /></Protected>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster theme="dark" position="top-right" richColors />
    </AuthProvider>
  );
}
