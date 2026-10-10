import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { Plus, Trash2, Upload } from "lucide-react";
import { api, fetcher, errMsg } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import CompositionPreview from "@/components/CompositionPreview";

const DEF = { name: "", primary_color: "#DC2626", secondary_color: "#0F172A", logo_corner: "top-right", ticker_label: "તાજા સમાચાર", default_ticker: "", subtitle_style: { enabled: true, size: 42, color: "#FFFFFF", background: "box", position: "bottom" } };

export const ColorField = ({ id, label, value, onChange }) => (
  <div><Label className="text-xs text-slate-400">{label}</Label>
    <div className="mt-1 flex items-center gap-2"><input data-testid={`${id}-color`} type="color" value={value} onChange={(e) => onChange(e.target.value.toUpperCase())} className="h-9 w-10 cursor-pointer rounded border border-[#263346] bg-transparent" />
      <Input value={value} onChange={(e) => onChange(e.target.value)} className="mono h-9 bg-[#0B0F19] text-xs" /></div></div>
);

function Editor({ channel, onSaved }) {
  const [c, setC] = useState(channel || DEF);
  const set = (k) => (v) => setC({ ...c, [k]: v });
  const save = async () => {
    const body = { name: c.name, primary_color: c.primary_color, secondary_color: c.secondary_color, logo_corner: c.logo_corner, ticker_label: c.ticker_label, default_ticker: c.default_ticker, subtitle_style: c.subtitle_style };
    try {
      const { data } = c.id ? await api.patch(`/channels/${c.id}`, body) : await api.post("/channels", body);
      setC(data); toast.success("Channel saved"); onSaved(data);
    } catch (e) { toast.error(errMsg(e)); }
  };
  const logo = async (file) => {
    if (!c.id) return toast.error("Save the channel first");
    const fd = new FormData(); fd.append("file", file);
    try { const { data } = await api.post(`/channels/${c.id}/logo`, fd); setC(data); onSaved(data); toast.success("Logo uploaded"); } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div className="grid gap-6 lg:grid-cols-12">
      <div className="card-surface space-y-4 p-5 lg:col-span-5">
        <div><Label>Channel name</Label><Input data-testid="channel-name-input" value={c.name} onChange={(e) => set("name")(e.target.value)} className="gu mt-1 bg-[#0B0F19]" placeholder="e.g. ગુજરાત લાઇવ" /></div>
        <div className="grid grid-cols-2 gap-3"><ColorField id="channel-primary" label="Primary" value={c.primary_color} onChange={set("primary_color")} /><ColorField id="channel-secondary" label="Secondary" value={c.secondary_color} onChange={set("secondary_color")} /></div>
        <div><Label className="text-xs text-slate-400">Logo corner</Label>
          <div className="mt-1 flex gap-2">{["top-left", "top-right"].map((k) => <Button key={k} size="sm" variant="outline" data-testid={`logo-corner-${k}`} onClick={() => set("logo_corner")(k)} className={`bg-transparent ${c.logo_corner === k ? "border-red-500 text-white" : "border-[#374151] text-slate-400"}`}>{k}</Button>)}</div></div>
        <div><Label className="text-xs text-slate-400">Ticker label</Label><Input data-testid="channel-ticker-label-input" value={c.ticker_label} onChange={(e) => set("ticker_label")(e.target.value)} className="gu mt-1 bg-[#0B0F19]" /></div>
        <div><Label className="text-xs text-slate-400">Default ticker (one item per line)</Label><Textarea data-testid="channel-ticker-input" rows={3} value={c.default_ticker} onChange={(e) => set("default_ticker")(e.target.value)} className="gu mt-1 bg-[#0B0F19]" /></div>
        <label className="flex cursor-pointer items-center gap-2 rounded-md border border-dashed border-[#374151] p-3 text-sm text-slate-300"><Upload className="h-4 w-4" /> {c.logo_url ? "Replace logo" : "Upload logo"} <span className="text-xs text-slate-500">(transparent PNG/WebP, ≤ 2 MB)</span>
          <input data-testid="channel-logo-input" type="file" accept="image/png,image/webp,image/jpeg" className="hidden" onChange={(e) => e.target.files?.[0] && logo(e.target.files[0])} /></label>
        <Button data-testid="channel-save-btn" onClick={save} disabled={!c.name} className="w-full bg-red-600 hover:bg-red-700">Save channel</Button>
      </div>
      <div className="lg:col-span-7"><CompositionPreview logoUrl={c.logo_url} headline="ચેનલ બ્રાન્ડિંગ પૂર્વાવલોકન" location="સુરત" subtitle="અહીં ગુજરાતી સબટાઇટલ દેખાશે." subtitleStyle={c.subtitle_style}
        branding={{ channel_name: c.name, primary_color: c.primary_color, secondary_color: c.secondary_color, logo_corner: c.logo_corner, ticker_label: c.ticker_label, ticker_text: c.default_ticker }} /></div>
    </div>
  );
}

export default function Channels() {
  const { data, mutate } = useSWR("/channels", fetcher);
  const [sel, setSel] = useState(null);
  const del = async (id) => { try { await api.delete(`/channels/${id}`); mutate(); setSel(null); } catch (e) { toast.error(errMsg(e)); } };
  return (
    <div className="space-y-6 fade-up">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><div className="eyebrow">Brand presets</div><h1 className="mt-1 text-3xl font-bold text-white">Channels</h1></div>
        <Button data-testid="new-channel-btn" onClick={() => setSel("new")} className="bg-red-600 hover:bg-red-700"><Plus /> New channel</Button>
      </div>
      <div className="flex flex-wrap gap-2">
        {(data?.items || []).map((c) => (
          <div key={c.id} className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${sel?.id === c.id ? "border-red-500 bg-[#182232]" : "border-[#263346]"}`}>
            <button data-testid={`channel-item-${c.id}`} onClick={() => setSel(c)} className="gu flex items-center gap-2 text-white"><span className="h-3 w-3 rounded-sm" style={{ background: c.primary_color }} />{c.name}</button>
            <button data-testid={`delete-channel-btn-${c.id}`} onClick={() => del(c.id)} className="text-slate-500 hover:text-red-300"><Trash2 className="h-3.5 w-3.5" /></button>
          </div>))}
        {data && !data.items.length && sel !== "new" && <p className="text-sm text-slate-500">No channels yet. Create one to reuse your logo, colours and ticker.</p>}
      </div>
      {sel && <Editor key={sel === "new" ? "new" : sel.id} channel={sel === "new" ? null : sel} onSaved={(c) => { mutate(); setSel(c); }} />}
    </div>
  );
}
