import { NavLink, Outlet, useNavigate } from "react-router-dom";
import useSWR from "swr";
import { LayoutDashboard, UserSquare2, Tv, Clapperboard, ListChecks, Film, CreditCard, Settings, ShieldCheck, LogOut, Plus, MailWarning } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { fetcher, api, errMsg } from "@/lib/api";
import { Button } from "@/components/ui/button";

const NAV = [
  ["/app", "Dashboard", LayoutDashboard, true],
  ["/app/new", "New video", Clapperboard],
  ["/app/jobs", "Jobs", ListChecks],
  ["/app/library", "Video library", Film],
  ["/app/anchors", "Anchor library", UserSquare2],
  ["/app/channels", "Channels", Tv],
  ["/app/billing", "Billing & credits", CreditCard],
  ["/app/account", "Account & privacy", Settings],
];

export const Logo = () => (
  <div className="flex items-center gap-2.5">
    <div className="flex h-8 w-8 items-center justify-center rounded-md bg-red-600 font-display text-sm font-extrabold text-white">AI</div>
    <div className="leading-tight">
      <div className="font-display text-base font-bold tracking-tight text-white">AnchorAI <span className="text-red-500">News</span></div>
      <div className="gu text-[10px] text-slate-400">ગુજરાતી સમાચાર સ્ટુડિયો</div>
    </div>
  </div>
);

function VerifyBanner() {
  const resend = async () => {
    try { await api.post("/auth/resend-verification"); toast.success("Verification email sent"); }
    catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div data-testid="verify-email-banner" className="flex flex-wrap items-center gap-3 border-b border-amber-500/30 bg-amber-500/10 px-6 py-2.5 text-sm text-amber-200">
      <MailWarning className="h-4 w-4" /> Verify your email to unlock your 30 trial credits and video generation.
      <button data-testid="resend-verification-btn" onClick={resend} className="font-semibold underline underline-offset-4">Resend email</button>
    </div>
  );
}

export default function AppLayout() {
  const { user, signOut } = useAuth();
  const nav = useNavigate();
  const { data: bal } = useSWR("/billing/balance", fetcher, { refreshInterval: 15000 });
  const items = user?.role === "admin" ? [...NAV, ["/app/admin", "Admin", ShieldCheck]] : NAV;

  return (
    <div className="flex min-h-screen bg-[#0B0F19]">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-[#263346] bg-[#0D1220] p-5 lg:flex">
        <Logo />
        <Button data-testid="sidebar-new-video-btn" onClick={() => nav("/app/new")} className="mt-8 w-full bg-red-600 hover:bg-red-700">
          <Plus /> New news video
        </Button>
        <nav className="mt-6 flex flex-1 flex-col gap-1">
          {items.map(([to, label, Icon, end]) => (
            <NavLink key={to} to={to} end={end} data-testid={`nav-${label.toLowerCase().replace(/[^a-z]+/g, "-")}-link`}
              className={({ isActive }) => `flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${isActive ? "bg-[#182232] text-white" : "text-slate-400 hover:bg-[#141c2b] hover:text-white"}`}>
              <Icon className="h-4 w-4" /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-[#263346] pt-4 text-xs text-slate-400">
          <div className="truncate text-slate-200" data-testid="sidebar-user-email">{user?.email}</div>
          <button data-testid="logout-btn" onClick={async () => { await signOut(); nav("/"); }} className="mt-2 flex items-center gap-2 hover:text-white">
            <LogOut className="h-3.5 w-3.5" /> Sign out
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex items-center justify-between border-b border-[#263346] bg-[#0B0F19]/90 px-4 py-3 backdrop-blur-xl sm:px-6">
          <div className="lg:hidden"><Logo /></div>
          <div className="hidden items-center gap-2 text-xs text-slate-400 lg:flex"><span className="live-dot" /> Studio online · Gujarati (gu-IN) · 16:9 1080p</div>
          <div className="flex items-center gap-3">
            <NavLink to="/app/billing" data-testid="credit-balance-badge" className="rounded-full border border-[#263346] bg-[#182232] px-3 py-1 text-sm">
              {bal?.unlimited ? <><span className="font-semibold text-emerald-300">∞ Unlimited</span> <span className="text-slate-400">credits</span></>
                : <><span className="font-semibold text-white">{bal?.available ?? "—"}</span> <span className="text-slate-400">credits</span></>}
              {bal?.reserved ? <span className="ml-1 text-amber-300">({bal.reserved} held)</span> : null}
            </NavLink>
          </div>
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b border-[#263346] px-3 py-2 lg:hidden">
          {items.map(([to, label, , end]) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `whitespace-nowrap rounded px-3 py-1.5 text-xs ${isActive ? "bg-[#182232] text-white" : "text-slate-400"}`}>{label}</NavLink>
          ))}
          <button onClick={async () => { await signOut(); nav("/"); }} className="whitespace-nowrap px-3 text-xs text-slate-400">Sign out</button>
        </nav>
        {user && !user.email_verified && <VerifyBanner />}
        <main className="flex-1 p-4 sm:p-6 lg:p-8"><Outlet /></main>
      </div>
    </div>
  );
}
