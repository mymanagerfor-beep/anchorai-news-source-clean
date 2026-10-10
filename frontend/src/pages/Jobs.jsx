import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { RotateCcw, XCircle, Download } from "lucide-react";
import { api, fetcher, errMsg, fmtDate } from "@/lib/api";
import { StatusChip, StageBar, isActive } from "@/components/StatusChip";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

const FILTERS = ["all", "queued", "validating", "generating", "retrieving", "rendering", "completed", "failed", "cancelled"];

export async function openVideo(videoId, inline) {
  const { data } = await api.post(`/videos/${videoId}/download-url${inline ? "?inline=true" : ""}`);
  return data.url;
}

function JobDrawer({ id, onClose, onChanged }) {
  const { data: j, mutate } = useSWR(id ? `/jobs/${id}` : null, fetcher, { refreshInterval: (d) => (d && isActive(d.status) ? 4000 : 0) });
  const [src, setSrc] = useState(null);
  const act = async (path, msg) => { try { await api.post(`/jobs/${id}/${path}`); toast.success(msg); mutate(); onChanged(); } catch (e) { toast.error(errMsg(e)); } };
  const vid = j?.final?.video_asset_id;
  return (
    <Sheet open={!!id} onOpenChange={(o) => { if (!o) { setSrc(null); onClose(); } }}>
      <SheetContent className="w-full overflow-y-auto border-[#263346] bg-[#111827] sm:max-w-xl">
        <SheetHeader><SheetTitle>{j?.project_name}</SheetTitle></SheetHeader>
        {j && <div className="mt-4 space-y-5 text-sm" data-testid="job-detail-drawer">
          <div className="flex items-center gap-3"><StatusChip status={j.status} testId="job-detail-status" /><span className="mono text-xs text-slate-500">{j.id}</span></div>
          <StageBar status={j.status} />
          {j.provider_status && <div className="text-xs text-slate-400">Provider status: <span className="mono text-slate-200" data-testid="job-provider-status">{j.provider_status}</span></div>}
          {j.error_message && <div className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-red-200" data-testid="job-error-message"><b className="mono text-xs">{j.error_code}</b><p className="mt-1">{j.error_message}</p></div>}
          <div className="grid grid-cols-2 gap-2 text-xs">
            {[["Anchor", j.anchor_name], ["Template", "Breaking News"], ["Submitted", fmtDate(j.created_at)], ["Attempts", j.attempt_count], ["Reserved", `${j.reserved_credits} credits`], ["Charged", j.final_credits == null ? "—" : `${j.final_credits} credits`], ["Avatar provider", j.provider], ["Subtitle timing", j.final?.subtitle_timing?.replace("_", " ") || "—"]].map(([k, v]) => (
              <div key={k} className="rounded border border-[#263346] p-2"><div className="text-slate-500">{k}</div><div className="text-slate-200">{v}</div></div>))}
          </div>
          {vid && <div className="space-y-2">
            {src ? <video data-testid="job-video-player" src={src} controls className="w-full rounded" /> : <Button data-testid="job-preview-btn" onClick={async () => setSrc(await openVideo(vid, true))} className="w-full bg-red-600 hover:bg-red-700">Preview final video</Button>}
            <Button variant="outline" data-testid="job-download-btn" onClick={async () => { window.location.href = await openVideo(vid, false); }} className="w-full border-[#374151] bg-transparent"><Download /> Download MP4</Button>
          </div>}
          <div className="flex gap-2">
            {isActive(j.status) && <Button variant="outline" data-testid="job-cancel-btn" onClick={() => act("cancel", "Cancellation requested")} className="border-[#374151] bg-transparent"><XCircle /> Cancel job</Button>}
            {j.retry_safe && ["failed", "cancelled"].includes(j.status) && <Button data-testid="job-retry-btn" onClick={() => act("retry", "Job re-queued")} className="bg-red-600 hover:bg-red-700"><RotateCcw /> Retry</Button>}
          </div>
          <div><div className="eyebrow mb-2">Timeline</div>
            <ol className="space-y-2 border-l border-[#263346] pl-4">{[...(j.events || [])].reverse().map((e, i) => <li key={i} className="text-xs"><span className="text-slate-500">{fmtDate(e.at)}</span> · <span className="capitalize text-slate-200">{e.status}</span> — <span className="text-slate-400">{e.msg}</span></li>)}</ol></div>
          <div><div className="eyebrow mb-2">Script</div><p className="gu whitespace-pre-wrap rounded border border-[#263346] bg-[#0B0F19] p-3 text-slate-200">{j.script}</p></div>
        </div>}
      </SheetContent>
    </Sheet>
  );
}

export default function Jobs() {
  const [filter, setFilter] = useState("all");
  const [open, setOpen] = useState(null);
  const { data, mutate } = useSWR(`/jobs${filter === "all" ? "" : `?status=${filter}`}`, fetcher, { refreshInterval: 5000 });
  return (
    <div className="space-y-6 fade-up">
      <div><div className="eyebrow">Live production queue</div><h1 className="mt-1 text-3xl font-bold text-white">Video jobs</h1></div>
      <div className="flex flex-wrap gap-1">{FILTERS.map((f) => <button key={f} data-testid={`jobs-filter-${f}`} onClick={() => setFilter(f)} className={`rounded-md px-3 py-1.5 text-xs capitalize ${filter === f ? "bg-[#182232] text-white" : "text-slate-400 hover:text-white"}`}>{f}</button>)}</div>
      <div className="card-surface overflow-x-auto">
        <table className="w-full min-w-[820px] text-sm">
          <thead><tr className="text-left text-xs text-slate-500"><th className="p-3">Job</th><th>Project</th><th>Anchor</th><th>Submitted</th><th>Status</th><th className="w-44">Progress</th><th className="pr-3 text-right">Credits</th></tr></thead>
          <tbody>
            {(data?.items || []).map((j) => (
              <tr key={j.id} data-testid={`job-row-${j.id}`} onClick={() => setOpen(j.id)} className="cursor-pointer border-t border-[#263346] hover:bg-[#1F2B3E]/50">
                <td className="mono p-3 text-xs text-slate-400">{j.id.slice(0, 8)}</td>
                <td className="text-white">{j.project_name}<div className="text-xs text-slate-500">Breaking News</div></td>
                <td className="text-slate-300">{j.anchor_name}</td>
                <td className="text-slate-400">{fmtDate(j.created_at)}</td>
                <td><StatusChip status={j.status} testId={`job-status-${j.id}`} />{j.error_code && <div className="mono mt-1 text-[11px] text-red-300">{j.error_code}</div>}</td>
                <td><StageBar status={j.status} /><div className="mt-1 truncate text-[11px] text-slate-500">{j.provider_status || ""}</div></td>
                <td className="pr-3 text-right text-slate-300">{j.final_credits != null ? j.final_credits : `~${j.estimated_credits}`}</td>
              </tr>))}
            {data && !data.items.length && <tr><td colSpan={7} className="p-10 text-center text-slate-500">No jobs here yet.</td></tr>}
          </tbody>
        </table>
      </div>
      <JobDrawer id={open} onClose={() => setOpen(null)} onChanged={mutate} />
    </div>
  );
}
