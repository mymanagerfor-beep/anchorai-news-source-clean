import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { CheckCircle2, XCircle, RefreshCw } from "lucide-react";
import { api, fetcher, errMsg, fmtDate } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const Ok = ({ ok, label }) => <div className="flex items-center gap-2 text-sm">{ok ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <XCircle className="h-4 w-4 text-red-400" />}<span className="text-slate-200">{label}</span></div>;

function UpiReview() {
  const { data, mutate } = useSWR("/admin/payments?status=pending_review", fetcher, { refreshInterval: 20000 });
  const [notes, setNotes] = useState({});
  const review = async (id, action) => {
    try { await api.post(`/admin/payments/${id}/review`, { action, note: notes[id] || "" }); toast.success(action === "approve" ? "Approved: credits added" : "Payment rejected"); mutate(); }
    catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div className="card-surface p-5" data-testid="admin-upi-review">
      <h3 className="font-semibold text-white">UPI payments awaiting confirmation</h3>
      <p className="mt-1 text-xs text-slate-500">Check that the amount and UTR arrived in your UPI app before approving. Approving adds the pack credits once; rejecting adds nothing.</p>
      <div className="mt-3 space-y-2">
        {(data?.items || []).map((p) => (
          <div key={p.id} className="flex flex-wrap items-center gap-3 rounded border border-[#263346] p-3 text-sm" data-testid={`upi-pending-${p.id}`}>
            <div className="min-w-[220px] flex-1"><div className="text-white">₹{p.amount} · {p.credits} credits · {p.payer_email}</div>
              <div className="mono text-xs text-amber-200">UTR {p.upi_ref}{p.payer_name ? ` · ${p.payer_name}` : ""}</div><div className="text-xs text-slate-500">{fmtDate(p.created_at)}</div></div>
            <Input placeholder="Note (optional)" value={notes[p.id] || ""} onChange={(e) => setNotes({ ...notes, [p.id]: e.target.value })} className="h-8 w-44 bg-[#0B0F19] text-xs" />
            <Button size="sm" data-testid={`upi-approve-${p.id}`} onClick={() => review(p.id, "approve")} className="bg-emerald-600 hover:bg-emerald-700">Approve</Button>
            <Button size="sm" variant="outline" data-testid={`upi-reject-${p.id}`} onClick={() => review(p.id, "reject")} className="border-[#374151] bg-transparent text-red-300">Reject</Button>
          </div>))}
        {data && !data.items.length && <p className="py-4 text-center text-sm text-slate-500">No pending UPI payments.</p>}
      </div>
    </div>
  );
}

export default function Admin() {
  const { data: h, mutate, isValidating } = useSWR("/admin/health", fetcher);
  const [q, setQ] = useState("");
  const { data: ws, mutate: mWs } = useSWR(`/admin/workspaces?q=${encodeURIComponent(q)}`, fetcher);
  const { data: audit } = useSWR("/admin/audit", fetcher);
  const { data: rec } = useSWR("/admin/reconcile", fetcher);
  const [adj, setAdj] = useState({ workspace_id: "", amount: "", reason: "" });
  const submit = async () => {
    try { await api.post("/admin/credits/adjust", { ...adj, amount: parseInt(adj.amount, 10) }); toast.success("Adjustment recorded"); setAdj({ workspace_id: "", amount: "", reason: "" }); mWs(); }
    catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div className="space-y-6 fade-up">
      <div className="flex items-end justify-between"><div><div className="eyebrow">Platform operations</div><h1 className="mt-1 text-3xl font-bold text-white">Admin</h1></div>
        <Button variant="outline" data-testid="admin-refresh-health" onClick={() => mutate()} className="border-[#374151] bg-transparent"><RefreshCw className={isValidating ? "animate-spin" : ""} /> Re-check</Button></div>
      <div className="card-surface grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-4" data-testid="admin-health-panel">
        <Ok ok={h?.provider?.configured} label="AI provider credentials" /><Ok ok={h?.provider?.reachable && h?.provider?.auth_ok} label="AI provider reachable" />
        <Ok ok={h?.storage?.ok} label="Private object storage" /><Ok ok={h?.ffmpeg?.ok && h?.gujarati_font} label="FFmpeg + Gujarati font" />
        <Ok ok={h?.payments_configured} label="Razorpay keys" /><Ok ok={h?.webhook_secret_configured} label="Payment webhook secret" />
        <Ok ok={h?.email_configured} label="Transactional email" /><div className="text-sm text-slate-400">Disk free: {h?.disk_free_gb} GB</div>
        {(h?.issues || []).length > 0 && <ul className="col-span-full space-y-1 rounded border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-200" data-testid="admin-config-issues">{h.issues.map((i) => <li key={i}>• {i}</li>)}</ul>}
        <div className="col-span-full text-xs text-slate-500">Avatar: {h?.provider?.provider} · TTS: {h?.provider?.tts} · Ledger mismatches: <span data-testid="ledger-mismatches">{rec?.mismatches?.length ?? "—"}</span></div>
      </div>
      <UpiReview />
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="card-surface p-5">
          <h3 className="font-semibold text-white">Give credits to a user</h3>
          <p className="mt-1 text-xs text-slate-500">Pick a user, choose an amount (negative to deduct) and give a reason. Every change is written to the ledger and audit log. Your admin workspace has unlimited credits.</p>
          <Input data-testid="admin-search-input" placeholder="Search user email" value={q} onChange={(e) => setQ(e.target.value)} className="mt-3 bg-[#0B0F19]" />
          <div className="mt-2 max-h-56 space-y-1 overflow-y-auto">{(ws?.items || []).filter((x) => x.workspace).map((x) => (
            <button key={x.user.id} disabled={x.workspace.unlimited_credits} data-testid={`admin-ws-${x.workspace.id}`} onClick={() => setAdj({ ...adj, workspace_id: x.workspace.id })} className={`flex w-full justify-between rounded px-3 py-1.5 text-left text-xs ${adj.workspace_id === x.workspace.id ? "bg-red-500/15 text-white" : "text-slate-300 hover:bg-[#1F2B3E]"}`}>
              <span>{x.user.email} · {x.workspace.name}{x.user.role === "admin" ? " · admin" : ""}{!x.user.email_verified ? " · unverified" : ""}</span><span className={x.workspace.unlimited_credits ? "text-emerald-300" : ""}>{x.workspace.unlimited_credits ? "∞ unlimited" : `${x.workspace.credits_balance} cr`}</span></button>))}</div>
          <div className="mt-3 flex flex-wrap gap-2">{[30, 60, 120, 600].map((n) => <Button key={n} size="sm" variant="outline" data-testid={`admin-preset-${n}`} onClick={() => setAdj({ ...adj, amount: String(n), reason: adj.reason || "Credits granted by admin" })} className="border-[#374151] bg-transparent">+{n}</Button>)}</div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <Input data-testid="admin-adjust-amount" type="number" placeholder="± credits" value={adj.amount} onChange={(e) => setAdj({ ...adj, amount: e.target.value })} className="bg-[#0B0F19]" />
            <Input data-testid="admin-adjust-reason" placeholder="Reason (required)" value={adj.reason} onChange={(e) => setAdj({ ...adj, reason: e.target.value })} className="col-span-2 bg-[#0B0F19]" />
          </div>
          <Button data-testid="admin-adjust-submit" disabled={!adj.workspace_id || !adj.amount || adj.reason.length < 5} onClick={submit} className="mt-3 bg-red-600 hover:bg-red-700">Apply credits</Button>
        </div>
        <div className="card-surface p-5"><h3 className="font-semibold text-white">Audit events</h3>
          <div className="mt-3 max-h-80 space-y-1 overflow-y-auto text-xs" data-testid="admin-audit-list">{(audit?.items || []).map((e) => <div key={e.id} className="flex justify-between gap-3 border-b border-[#263346] py-1.5"><span className="mono text-slate-200">{e.action}</span><span className="truncate text-slate-500">{e.target?.slice(0, 8)} · {fmtDate(e.created_at)}</span></div>)}</div></div>
      </div>
    </div>
  );
}
