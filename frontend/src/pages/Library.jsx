import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { Download, Pencil, Trash2, Play, FileText } from "lucide-react";
import { api, fetcher, errMsg, fmtDate, API } from "@/lib/api";
import { openVideo } from "@/pages/Jobs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

async function downloadSubs(id, fmt) {
  const { data } = await api.get(`/videos/${id}/subtitles.${fmt}`, { responseType: "blob" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(data); a.download = `subtitles-${id.slice(0, 8)}.${fmt}`; a.click();
}

export default function Library() {
  const { data, mutate } = useSWR("/videos", fetcher);
  const [player, setPlayer] = useState(null);
  const [rename, setRename] = useState(null);
  const [details, setDetails] = useState(null);
  const play = async (v) => { try { setPlayer({ v, src: await openVideo(v.id, true) }); } catch (e) { toast.error(errMsg(e)); } };
  const del = async (v) => { if (!window.confirm("Delete this video? The file is removed from your library and scheduled for storage purge.")) return; try { await api.delete(`/videos/${v.id}`); mutate(); toast.success("Video deleted"); } catch (e) { toast.error(errMsg(e)); } };
  const doRename = async () => { try { await api.patch(`/projects/${rename.project_id}`, { name: rename.name }); setRename(null); mutate(); } catch (e) { toast.error(errMsg(e)); } };
  const showDetails = async (v) => { try { const { data: j } = await api.get(`/jobs/${v.job_id}`); setDetails(j); } catch (e) { toast.error(errMsg(e)); } };
  return (
    <div className="space-y-6 fade-up">
      <div><div className="eyebrow">Finished bulletins</div><h1 className="mt-1 text-3xl font-bold text-white">Video library</h1><p className="mt-1 text-sm text-slate-400">Downloads use short-lived authorized links. Files are never publicly exposed.</p></div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(data?.items || []).map((v) => (
          <div key={v.id} className="card-surface overflow-hidden" data-testid={`video-card-${v.id}`}>
            <button onClick={() => play(v)} data-testid={`video-play-btn-${v.id}`} className="group relative flex aspect-video w-full items-center justify-center bg-[#0B0F19]">
              <div className="absolute left-3 top-3 rounded bg-red-600 px-2 py-0.5 text-[10px] font-bold">BREAKING NEWS</div>
              <Play className="h-10 w-10 text-white/70 transition-transform group-hover:scale-110" />
              <div className="gu absolute bottom-3 left-3 right-3 truncate text-left text-sm text-slate-200">{v.headline}</div>
            </button>
            <div className="space-y-3 p-4">
              <div className="truncate font-semibold text-white">{v.project_name}</div>
              <div className="text-xs text-slate-400">{fmtDate(v.created_at)} · {v.duration?.toFixed(1)}s · {v.width}×{v.height} · {(v.file_size / 1e6).toFixed(1)} MB · <span className="text-amber-300">{v.credits_charged} credits</span></div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" data-testid={`download-mp4-btn-${v.id}`} onClick={async () => { window.location.href = await openVideo(v.id, false); }} className="bg-red-600 hover:bg-red-700"><Download /> MP4</Button>
                <Button size="sm" variant="outline" data-testid={`download-srt-btn-${v.id}`} onClick={() => downloadSubs(v.id, "srt")} className="border-[#374151] bg-transparent">SRT</Button>
                <Button size="sm" variant="outline" data-testid={`download-vtt-btn-${v.id}`} onClick={() => downloadSubs(v.id, "vtt")} className="border-[#374151] bg-transparent">VTT</Button>
                <Button size="sm" variant="ghost" data-testid={`video-details-btn-${v.id}`} onClick={() => showDetails(v)}><FileText /></Button>
                <Button size="sm" variant="ghost" data-testid={`rename-video-btn-${v.id}`} onClick={() => setRename({ project_id: v.project_id, name: v.project_name })}><Pencil /></Button>
                <Button size="sm" variant="ghost" data-testid={`delete-video-btn-${v.id}`} onClick={() => del(v)} className="text-red-300"><Trash2 /></Button>
              </div>
            </div>
          </div>))}
        {data && !data.items.length && <div className="card-surface col-span-full p-10 text-center text-slate-500">No finished videos yet. Completed jobs appear here.</div>}
      </div>
      <Dialog open={!!player} onOpenChange={() => setPlayer(null)}>
        <DialogContent className="max-w-5xl border-[#263346] bg-[#111827]"><DialogHeader><DialogTitle>{player?.v.project_name}</DialogTitle></DialogHeader>
          {player && <video data-testid="library-video-player" src={player.src} controls autoPlay className="w-full rounded" />}</DialogContent>
      </Dialog>
      <Dialog open={!!rename} onOpenChange={() => setRename(null)}>
        <DialogContent className="border-[#263346] bg-[#111827]"><DialogHeader><DialogTitle>Rename project</DialogTitle></DialogHeader>
          <Input data-testid="rename-input" value={rename?.name || ""} onChange={(e) => setRename({ ...rename, name: e.target.value })} className="bg-[#0B0F19]" />
          <Button data-testid="rename-save-btn" onClick={doRename} className="bg-red-600 hover:bg-red-700">Save</Button></DialogContent>
      </Dialog>
      <Dialog open={!!details} onOpenChange={() => setDetails(null)}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto border-[#263346] bg-[#111827]"><DialogHeader><DialogTitle>Script & settings</DialogTitle></DialogHeader>
          {details && <div className="space-y-3 text-sm" data-testid="video-details">
            <p className="gu whitespace-pre-wrap rounded border border-[#263346] bg-[#0B0F19] p-3">{details.script}</p>
            <div className="text-xs text-slate-400">Voice: {details.settings?.voice} · Reserved {details.reserved_credits} · Charged {details.final_credits} credits · Timing: {details.final?.subtitle_timing}</div>
            <pre className="mono max-h-64 overflow-auto rounded bg-[#0B0F19] p-3 text-[11px] text-slate-400">{JSON.stringify(details.settings?.branding, null, 2)}</pre>
          </div>}</DialogContent>
      </Dialog>
      <span className="hidden">{API}</span>
    </div>
  );
}
