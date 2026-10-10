import { useState } from "react";
import { useNavigate } from "react-router-dom";
import useSWR from "swr";
import { toast } from "sonner";
import { api, fetcher, errMsg, fmtDate } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function Account() {
  const { data, mutate } = useSWR("/account", fetcher);
  const { data: ws } = useSWR("/workspaces/current", fetcher);
  const { data: anchors } = useSWR("/anchors?include_deleted=true", fetcher);
  const { signOut } = useAuth();
  const nav = useNavigate();
  const [del, setDel] = useState({ password: "", confirm: "" });
  const reqDeletion = async (scope) => {
    if (!window.confirm(`Delete ${scope.replace("_", " ")} in this workspace? This cannot be undone.`)) return;
    try { await api.post("/account/data-deletion", { scope }); toast.success("Data deletion completed"); mutate(); } catch (e) { toast.error(errMsg(e)); }
  };
  const deleteAccount = async () => {
    try { await api.post("/account/delete", del); toast.success("Account deleted"); await signOut(); nav("/"); } catch (e) { toast.error(errMsg(e)); }
  };
  const logoutAll = async () => { await api.post("/auth/logout-all"); await signOut(); nav("/login"); };
  return (
    <div className="space-y-6 fade-up">
      <div><div className="eyebrow">Profile, workspace & privacy</div><h1 className="mt-1 text-3xl font-bold text-white">Account</h1></div>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="card-surface space-y-2 p-5 text-sm">
          <h3 className="font-semibold text-white">Profile</h3>
          <div className="text-slate-300" data-testid="account-email">{data?.user.email} {data?.user.email_verified ? <span className="text-emerald-300">· verified</span> : <span className="text-amber-300">· not verified</span>}</div>
          <div className="text-slate-400">Name: {data?.user.name}</div>
          <div className="text-slate-400">Active sessions: {data?.active_sessions}</div>
          <Button size="sm" variant="outline" data-testid="logout-all-btn" onClick={logoutAll} className="mt-2 border-[#374151] bg-transparent">Sign out of all sessions</Button>
        </div>
        <div className="card-surface space-y-2 p-5 text-sm">
          <h3 className="font-semibold text-white">Workspace</h3>
          <div className="text-slate-300" data-testid="workspace-name">{ws?.name}</div>
          <div className="text-slate-400">Your role: <span className="capitalize">{ws?.role}</span> · Plan: pay-as-you-go credits</div>
          <div className="mt-2 space-y-1">{(ws?.members || []).map((m) => <div key={m.id} className="flex justify-between rounded border border-[#263346] px-3 py-1.5 text-xs"><span>{m.email}</span><span className="capitalize text-slate-400">{m.role}</span></div>)}</div>
          <p className="text-xs text-slate-500">Member invitations arrive in a later release.</p>
        </div>
      </div>
      <div className="card-surface p-5">
        <h3 className="font-semibold text-white">Consent & deletion history</h3>
        <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[600px] text-sm">
          <thead><tr className="text-left text-xs text-slate-500"><th className="py-2">Anchor</th><th>Likeness owner</th><th>Consent</th><th>Created</th><th>Deleted</th></tr></thead>
          <tbody>{(anchors?.items || []).map((a) => <tr key={a.id} className="border-t border-[#263346]"><td className="py-2 text-white">{a.display_name}</td><td className="text-slate-400">{a.authorized_by}</td><td className="capitalize text-slate-300">{a.consent_status}</td><td className="text-slate-400">{fmtDate(a.created_at)}</td><td className="text-slate-400">{a.deleted_at ? fmtDate(a.deleted_at) : "—"}</td></tr>)}</tbody>
        </table></div>
        <div className="mt-4 space-y-1 text-xs text-slate-400">{(data?.deletion_requests || []).map((d) => <div key={d.id}>{fmtDate(d.created_at)} · {d.type} · {d.status}</div>)}</div>
      </div>
      <div className="card-surface space-y-4 border-red-500/30 p-5">
        <h3 className="font-semibold text-red-300">Data deletion</h3>
        <p className="text-sm text-slate-400">Deleted files are removed from your workspace immediately and scheduled for purge from storage, subject to legal retention obligations. Copies already downloaded or shared cannot be recalled.</p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" data-testid="delete-videos-btn" onClick={() => reqDeletion("videos")} className="border-[#374151] bg-transparent">Delete all videos & audio</Button>
          <Button size="sm" variant="outline" data-testid="delete-anchors-btn" onClick={() => reqDeletion("anchors")} className="border-[#374151] bg-transparent">Delete all portraits</Button>
          <Button size="sm" variant="outline" data-testid="delete-all-media-btn" onClick={() => reqDeletion("all_media")} className="border-red-500/50 bg-transparent text-red-300">Delete all media</Button>
        </div>
        <div className="grid max-w-xl gap-3 border-t border-[#263346] pt-4 sm:grid-cols-3">
          <div><Label className="text-xs">Password</Label><Input type="password" data-testid="delete-account-password" value={del.password} onChange={(e) => setDel({ ...del, password: e.target.value })} className="mt-1 bg-[#0B0F19]" /></div>
          <div><Label className="text-xs">Type DELETE</Label><Input data-testid="delete-account-confirm" value={del.confirm} onChange={(e) => setDel({ ...del, confirm: e.target.value })} className="mt-1 bg-[#0B0F19]" /></div>
          <Button data-testid="delete-account-btn" disabled={del.confirm !== "DELETE" || !del.password} onClick={deleteAccount} className="self-end bg-red-600 hover:bg-red-700">Delete account</Button>
        </div>
      </div>
    </div>
  );
}
