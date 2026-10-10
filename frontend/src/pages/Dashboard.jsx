import { Link } from "react-router-dom";
import useSWR from "swr";
import { Film, Loader2, CheckCircle2, XCircle, Coins } from "lucide-react";
import { fetcher, fmtDate } from "@/lib/api";
import { StatusChip } from "@/components/StatusChip";
import { Button } from "@/components/ui/button";

const Metric = ({ icon: Icon, label, value, tone, id }) => (
  <div className="card-surface p-5" data-testid={`metric-${id}`}>
    <div className="flex items-center justify-between"><span className="eyebrow">{label}</span><Icon className={`h-4 w-4 ${tone}`} /></div>
    <div className="mt-3 font-display text-3xl font-bold text-white" data-testid={`metric-${id}-value`}>{value ?? "—"}</div>
  </div>
);

export const TxTable = ({ items }) => (
  <table className="w-full text-sm">
    <thead><tr className="text-left text-xs text-slate-500"><th className="py-2">Date</th><th>Type</th><th>Note</th><th className="text-right">Credits</th></tr></thead>
    <tbody>
      {items.map((t) => (
        <tr key={t.id} className="border-t border-[#263346]" data-testid={`ledger-row-${t.id}`}>
          <td className="py-2 text-slate-400">{fmtDate(t.created_at)}</td>
          <td className="capitalize text-slate-200">{t.type.replace("_", " ")}</td>
          <td className="max-w-[260px] truncate text-slate-400">{t.note}{t.job_id ? <span className="mono ml-1 text-[11px] text-slate-500">job {t.job_id.slice(0, 8)}</span> : null}</td>
          <td className={`text-right font-semibold ${t.amount >= 0 ? "text-emerald-300" : "text-red-300"}`}>{t.amount > 0 ? "+" : ""}{t.amount}</td>
        </tr>))}
      {!items.length && <tr><td colSpan={4} className="py-6 text-center text-slate-500">No transactions yet</td></tr>}
    </tbody>
  </table>
);

export default function Dashboard() {
  const { data: d } = useSWR("/dashboard", fetcher, { refreshInterval: 10000 });
  return (
    <div className="space-y-8 fade-up">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><div className="eyebrow">Newsroom overview</div><h1 className="mt-1 text-3xl font-bold text-white">Dashboard</h1></div>
        <Link to="/app/new"><Button data-testid="dashboard-new-video-btn" className="bg-red-600 hover:bg-red-700">Create news video</Button></Link>
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Metric id="generated" icon={Film} label="Videos generated" value={d?.videos_generated} tone="text-slate-300" />
        <Metric id="processing" icon={Loader2} label="Processing" value={d?.processing} tone="text-blue-400" />
        <Metric id="completed" icon={CheckCircle2} label="Completed jobs" value={d?.completed} tone="text-emerald-400" />
        <Metric id="failed" icon={XCircle} label="Failed jobs" value={d?.failed} tone="text-red-400" />
        <Metric id="credits" icon={Coins} label="Available credits" value={d?.unlimited_credits ? "∞ Unlimited" : d?.credits} tone="text-amber-300" />
      </div>
      <div className="grid gap-6 lg:grid-cols-12">
        <div className="card-surface p-5 lg:col-span-7">
          <div className="flex items-center justify-between"><h3 className="font-semibold text-white">Recent projects</h3><Link to="/app/jobs" className="text-xs text-slate-400 hover:text-white">All jobs →</Link></div>
          <div className="mt-4 divide-y divide-[#263346]">
            {(d?.recent_projects || []).map((p) => (
              <Link key={p.id} to={`/app/new/${p.id}`} data-testid={`recent-project-${p.id}`} className="flex items-center justify-between gap-3 py-3 hover:bg-[#1F2B3E]/40">
                <div className="min-w-0"><div className="truncate font-medium text-white">{p.name}</div><div className="gu truncate text-sm text-slate-400">{p.headline || "—"}</div></div>
                <div className="flex shrink-0 items-center gap-3"><span className="hidden text-xs text-slate-500 sm:block">{fmtDate(p.updated_at)}</span><StatusChip status={p.status} testId={`recent-project-status-${p.id}`} /></div>
              </Link>))}
            {d && !d.recent_projects.length && <p className="py-8 text-center text-sm text-slate-500">No projects yet. Upload an anchor portrait to get started.</p>}
          </div>
        </div>
        <div className="card-surface p-5 lg:col-span-5">
          <div className="flex items-center justify-between"><h3 className="font-semibold text-white">Recent credit activity</h3><Link to="/app/billing" className="text-xs text-slate-400 hover:text-white">Ledger →</Link></div>
          <div className="mt-2"><TxTable items={d?.recent_transactions || []} /></div>
        </div>
      </div>
    </div>
  );
}
