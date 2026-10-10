import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { Upload, Trash2, ShieldOff, ShieldCheck } from "lucide-react";
import { api, fetcher, errMsg, fmtDate } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";

function UploadDialog({ onDone }) {
  const { data: consent } = useSWR("/consent/text", fetcher);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ display_name: "", description: "", authorized_by: "", consent_basis: "self", consent_confirmed: false });
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!file) return toast.error("Choose a portrait image");
    const fd = new FormData();
    fd.append("file", file);
    Object.entries({ ...f, consent_version: consent.version }).forEach(([k, v]) => fd.append(k, v));
    setBusy(true);
    try { await api.post("/anchors", fd); toast.success("Anchor added with consent recorded"); setOpen(false); setFile(null); onDone(); }
    catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button data-testid="upload-anchor-btn" className="bg-red-600 hover:bg-red-700"><Upload /> Upload portrait</Button></DialogTrigger>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto border-[#263346] bg-[#111827]">
        <DialogHeader><DialogTitle>Add an authorized anchor</DialogTitle></DialogHeader>
        <div className="grid gap-5 md:grid-cols-2">
          <label className="flex aspect-[3/4] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-lg border border-dashed border-[#374151] bg-[#0B0F19] text-center text-sm text-slate-400" data-testid="anchor-dropzone">
            {file ? <img src={URL.createObjectURL(file)} alt="Selected portrait" className="h-full w-full object-cover" /> : <><Upload className="mb-2 h-6 w-6" />JPG, PNG or WebP<br />≤ 10 MB · short side ≥ 512 px<br /><span className="mt-2 text-xs">Front-facing, shoulders-up works best</span></>}
            <input data-testid="anchor-file-input" type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
          <div className="space-y-3">
            <div><Label>Display name</Label><Input data-testid="anchor-name-input" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} className="mt-1 bg-[#0B0F19]" /></div>
            <div><Label>Description</Label><Textarea data-testid="anchor-description-input" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} className="mt-1 bg-[#0B0F19]" rows={2} /></div>
            <div><Label>Person shown / likeness owner</Label><Input data-testid="anchor-owner-input" value={f.authorized_by} onChange={(e) => setF({ ...f, authorized_by: e.target.value })} placeholder="Full legal name" className="mt-1 bg-[#0B0F19]" /></div>
            <div><Label>Authorization basis</Label>
              <RadioGroup value={f.consent_basis} onValueChange={(v) => setF({ ...f, consent_basis: v })} className="mt-2 space-y-1">
                {Object.entries(consent?.bases || {}).map(([k, v]) => (
                  <label key={k} className="flex items-center gap-2 text-sm text-slate-300"><RadioGroupItem value={k} data-testid={`consent-basis-${k}`} /> {v}</label>))}
              </RadioGroup>
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-slate-300">
          <div className="mono text-[11px] text-amber-300">Consent statement · version {consent?.version}</div>
          <p className="mt-2">{consent?.text}</p>
          <label className="mt-3 flex items-start gap-2"><Checkbox data-testid="consent-checkbox" checked={f.consent_confirmed} onCheckedChange={(v) => setF({ ...f, consent_confirmed: !!v })} className="mt-0.5" /> I confirm this statement. Uploading a photo is not proof of authorization; I hold the documented permission.</label>
        </div>
        <Button data-testid="anchor-submit-btn" disabled={busy || !f.consent_confirmed || !f.display_name || !f.authorized_by} onClick={submit} className="bg-red-600 hover:bg-red-700">{busy ? "Validating & uploading…" : "Save anchor"}</Button>
      </DialogContent>
    </Dialog>
  );
}

const Confirm = ({ trigger, title, desc, action, onConfirm }) => (
  <AlertDialog>
    <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
    <AlertDialogContent className="border-[#263346] bg-[#111827]">
      <AlertDialogHeader><AlertDialogTitle>{title}</AlertDialogTitle><AlertDialogDescription>{desc}</AlertDialogDescription></AlertDialogHeader>
      <AlertDialogFooter><AlertDialogCancel className="bg-transparent">Cancel</AlertDialogCancel><AlertDialogAction data-testid="confirm-action-btn" onClick={onConfirm} className="bg-red-600 hover:bg-red-700">{action}</AlertDialogAction></AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
);

export default function Anchors() {
  const { data, mutate } = useSWR("/anchors", fetcher);
  const act = async (fn, msg) => { try { await fn(); toast.success(msg); mutate(); } catch (e) { toast.error(errMsg(e)); } };
  const REV = "Revocation blocks all future use and fails queued jobs safely. It cannot recall videos already downloaded or shared by others.";
  return (
    <div className="space-y-6 fade-up">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><div className="eyebrow">Consent-controlled</div><h1 className="mt-1 text-3xl font-bold text-white">Anchor library</h1><p className="mt-1 text-sm text-slate-400">Only portraits with active consent can be animated.</p></div>
        <UploadDialog onDone={mutate} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {(data?.items || []).map((a) => (
          <div key={a.id} className="card-surface overflow-hidden" data-testid={`anchor-card-${a.id}`}>
            <div className="aspect-[4/5] bg-[#0B0F19]">{a.image_url && <img src={a.image_url} alt={a.display_name} className={`h-full w-full object-cover ${a.usable ? "" : "opacity-40 grayscale"}`} />}</div>
            <div className="space-y-2 p-4">
              <div className="flex items-center justify-between gap-2"><div className="truncate font-semibold text-white">{a.display_name}</div>
                {a.usable ? <span className="flex items-center gap-1 text-xs text-emerald-300" data-testid={`anchor-consent-status-${a.id}`}><ShieldCheck className="h-3.5 w-3.5" />Consent active</span>
                  : <span className="flex items-center gap-1 text-xs text-red-300" data-testid={`anchor-consent-status-${a.id}`}><ShieldOff className="h-3.5 w-3.5" />Revoked</span>}</div>
              <p className="line-clamp-2 text-xs text-slate-400">{a.description || "—"}</p>
              <div className="text-xs text-slate-500">Likeness: {a.authorized_by} · {a.width}×{a.height} · {fmtDate(a.created_at)}</div>
              <div className="flex gap-2 pt-1">
                {a.usable && <Confirm title="Revoke consent?" desc={REV} action="Revoke consent" onConfirm={() => act(() => api.post(`/anchors/${a.id}/revoke-consent`), "Consent revoked")}
                  trigger={<Button size="sm" variant="outline" data-testid={`revoke-consent-btn-${a.id}`} className="border-[#374151] bg-transparent text-xs">Revoke</Button>} />}
                <Confirm title="Delete this anchor?" desc={`The portrait is removed from the library and scheduled for storage purge. ${REV}`} action="Delete" onConfirm={() => act(() => api.delete(`/anchors/${a.id}`), "Anchor deleted")}
                  trigger={<Button size="sm" variant="ghost" data-testid={`delete-anchor-btn-${a.id}`} className="text-xs text-red-300"><Trash2 className="h-3.5 w-3.5" /> Delete</Button>} />
              </div>
            </div>
          </div>))}
        {data && !data.items.length && <div className="card-surface col-span-full p-10 text-center text-slate-400">No anchors yet. Upload a front-facing portrait of someone who has authorized its use.</div>}
      </div>
    </div>
  );
}
