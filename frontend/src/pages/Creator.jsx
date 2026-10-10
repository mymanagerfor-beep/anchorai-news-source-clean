import { useEffect, useRef, useState, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import useSWR from "swr";
import { toast } from "sonner";
import { Check, Play, Save, Plus, X, ImageIcon, Loader2 } from "lucide-react";
import { api, fetcher, errMsg, newKey } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import CompositionPreview from "@/components/CompositionPreview";
import { ColorField } from "@/pages/Channels";

const STEPS = ["Anchor", "Script", "Narration", "Template", "Video settings", "Branding", "Consent & generate"];
const BLANK = { name: "Untitled bulletin", anchor_id: null, channel_id: null, script: "", headline: "", location: "", pronunciation: [], voice: "Sarah", template: "breaking_news",
  branding: { branding_enabled: true, channel_name: "", primary_color: "#DC2626", secondary_color: "#0F172A", logo_corner: "top-right", banner_text: "BREAKING NEWS", ticker_enabled: true, ticker_label: "તાજા સમાચાર", ticker_text: "", show_date: false, intro_enabled: false, outro_enabled: false },
  subtitle_style: { enabled: true, size: 42, color: "#FFFFFF", background: "box", position: "bottom" } };
const PAYLOAD = ["name", "anchor_id", "channel_id", "script", "headline", "location", "pronunciation", "voice", "branding", "subtitle_style"];

const Toggle = ({ id, label, checked, onChange, hint }) => (
  <label className="flex items-center justify-between gap-4 rounded-md border border-[#263346] bg-[#0B0F19] px-3 py-2.5 text-sm text-slate-200">
    <span>{label}{hint && <span className="block text-xs text-slate-500">{hint}</span>}</span><Switch data-testid={id} checked={checked} onCheckedChange={onChange} />
  </label>
);

function StepAnchor({ p, set, anchors, channels }) {
  const usable = anchors.filter((a) => a.usable);
  const pickChannel = (c) => set({ channel_id: c?.id || null, branding: c ? { ...p.branding, channel_name: c.name, primary_color: c.primary_color, secondary_color: c.secondary_color, logo_corner: c.logo_corner, ticker_label: c.ticker_label, ticker_text: p.branding.ticker_text || c.default_ticker } : p.branding,
    subtitle_style: c?.subtitle_style || p.subtitle_style });
  return (
    <div className="space-y-6">
      <div><Label>Project name</Label><Input data-testid="project-name-input" value={p.name} onChange={(e) => set({ name: e.target.value })} className="mt-1 max-w-md bg-[#0B0F19]" /></div>
      <div><Label>Authorized anchor</Label>
        <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {usable.map((a) => (
            <button key={a.id} data-testid={`anchor-card-select-${a.id}`} onClick={() => set({ anchor_id: a.id })} className={`overflow-hidden rounded-lg border text-left transition-colors ${p.anchor_id === a.id ? "border-red-500 ring-2 ring-red-500/40" : "border-[#263346] hover:border-[#374151]"}`}>
              <img src={a.image_url} alt={a.display_name} className="aspect-[4/5] w-full object-cover" /><div className="truncate p-2 text-sm text-white">{a.display_name}</div>
            </button>))}
        </div>
        {!usable.length && <p className="mt-2 text-sm text-amber-300">No consented anchors yet. Add one in the Anchor library first.</p>}
      </div>
      <div><Label>Channel preset (optional)</Label>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" data-testid="channel-select-none" onClick={() => pickChannel(null)} className={`bg-transparent ${!p.channel_id ? "border-red-500" : "border-[#374151]"}`}>None</Button>
          {channels.map((c) => <Button key={c.id} size="sm" variant="outline" data-testid={`channel-select-${c.id}`} onClick={() => pickChannel(c)} className={`gu bg-transparent ${p.channel_id === c.id ? "border-red-500" : "border-[#374151]"}`}>{c.name}</Button>)}
        </div></div>
    </div>
  );
}

function StepScript({ p, set, analysis }) {
  const pr = p.pronunciation || [];
  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-end justify-between"><Label>Gujarati news script</Label>
          <div className="flex gap-4 text-xs text-slate-400" data-testid="script-stats"><span data-testid="script-char-count">{analysis?.characters ?? 0} chars</span><span data-testid="script-word-count">{analysis?.words ?? 0} words</span>
            <span data-testid="script-duration" className={analysis?.estimated_seconds > analysis?.max_seconds ? "text-red-300" : "text-white"}>≈ {analysis?.estimated_seconds ?? 0}s / {analysis?.max_seconds ?? 60}s</span></div></div>
        <Textarea data-testid="gujarati-script-textarea" lang="gu" value={p.script} onChange={(e) => set({ script: e.target.value })} rows={11} placeholder="અહીં તમારી ગુજરાતી સમાચાર સ્ક્રિપ્ટ લખો…" className="gu mt-2 bg-[#0B0F19] text-base leading-loose sm:text-lg" />
        {analysis?.issues?.length > 0 && p.script && <ul className="mt-2 space-y-1 text-sm text-red-300" data-testid="script-issues">{analysis.issues.map((i) => <li key={i}>• {i}</li>)}</ul>}
        <p className="mt-2 text-xs text-slate-500">Duration is estimated at the configured Gujarati speaking rate; the final charge uses the real narration length. Sentence breaks (। . ? !) become subtitle and pause boundaries.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div><Label>Headline (lower-third)</Label><Input data-testid="headline-input" value={p.headline} onChange={(e) => set({ headline: e.target.value })} className="gu mt-1 bg-[#0B0F19]" /></div>
        <div><Label>Location label</Label><Input data-testid="location-input" value={p.location} onChange={(e) => set({ location: e.target.value })} className="gu mt-1 bg-[#0B0F19]" /></div>
      </div>
      <div>
        <Label>Pronunciation notes</Label><p className="text-xs text-slate-500">Changes the spoken narration only; subtitles keep your original spelling.</p>
        <div className="mt-2 space-y-2">
          {pr.map((x, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input data-testid={`pron-word-${i}`} value={x.word} placeholder="Word (e.g. GSRTC)" onChange={(e) => set({ pronunciation: pr.map((y, j) => (j === i ? { ...y, word: e.target.value } : y)) })} className="gu bg-[#0B0F19]" />
              <span className="text-slate-500">→</span>
              <Input data-testid={`pron-say-${i}`} value={x.say} placeholder="Say as (e.g. જી એસ આર ટી સી)" onChange={(e) => set({ pronunciation: pr.map((y, j) => (j === i ? { ...y, say: e.target.value } : y)) })} className="gu bg-[#0B0F19]" />
              <Button size="icon" variant="ghost" onClick={() => set({ pronunciation: pr.filter((_, j) => j !== i) })}><X /></Button>
            </div>))}
          <Button size="sm" variant="outline" data-testid="add-pronunciation-btn" onClick={() => set({ pronunciation: [...pr, { word: "", say: "" }] })} className="border-[#374151] bg-transparent"><Plus /> Add note</Button>
        </div>
      </div>
    </div>
  );
}

function StepVoice({ p, set }) {
  const { data } = useSWR("/voices", fetcher);
  const [loading, setLoading] = useState(null);
  const audio = useRef(null);
  const preview = async (v) => {
    setLoading(v);
    try { const { data: d } = await api.get(`/voices/${v}/preview`); audio.current.src = d.url; await audio.current.play(); }
    catch (e) { toast.error(errMsg(e)); } finally { setLoading(null); }
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 text-sm"><span className="rounded-full border border-[#263346] px-3 py-1">Language: <b className="gu">ગુજરાતી</b> (gu-IN)</span><span className="rounded-full border border-[#263346] px-3 py-1 text-slate-400">{data?.provider}</span></div>
      <div className="grid gap-3 sm:grid-cols-2">
        {(data?.voices || []).map((v) => (
          <div key={v.id} data-testid={`voice-option-${v.id}`} onClick={() => set({ voice: v.id })} className={`cursor-pointer rounded-lg border p-4 transition-colors ${p.voice === v.id ? "border-red-500 bg-red-500/5" : "border-[#263346] hover:border-[#374151]"}`}>
            <div className="flex items-center justify-between"><div><div className="font-semibold text-white">{v.label}</div><div className="text-xs capitalize text-slate-400">{v.gender} · {v.tone}</div></div>
              <Button size="sm" variant="outline" data-testid={`voice-preview-btn-${v.id}`} onClick={(e) => { e.stopPropagation(); preview(v.id); }} className="border-[#374151] bg-transparent">{loading === v.id ? <Loader2 className="animate-spin" /> : <Play />} Preview</Button></div>
          </div>))}
      </div>
      <audio ref={audio} className="hidden" data-testid="voice-preview-audio" />
      <p className="text-xs text-slate-500">Each voice was checked with a real Gujarati sample. Previews are generated once by the provider and cached. Speech speed is not offered because the provider does not support it on this model.</p>
    </div>
  );
}

const StepTemplate = () => (
  <div className="grid gap-3 sm:grid-cols-3">
    <div data-testid="template-breaking-news" className="rounded-lg border border-red-500 bg-red-500/5 p-4"><div className="flex items-center justify-between font-semibold text-white">Breaking News <Check className="h-4 w-4 text-red-400" /></div><p className="mt-1 text-xs text-slate-400">Red banner, Gujarati lower-third, ticker, subtitles, AI disclosure.</p></div>
    {["Daily Bulletin", "Explainer"].map((t) => <div key={t} className="rounded-lg border border-[#263346] p-4 opacity-50"><div className="font-semibold">{t}</div><p className="mt-1 text-xs text-slate-500">Coming later</p></div>)}
  </div>
);

function StepSettings({ p, set }) {
  const rows = [["Aspect ratio", "16:9 landscape"], ["Resolution", "1920 × 1080"], ["Language", "Gujarati (gu-IN)"], ["Container", "MP4"], ["Codecs", "H.264 video · AAC audio"]];
  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-2">{rows.map(([k, v]) => <div key={k} className="flex justify-between rounded-md border border-[#263346] px-3 py-2 text-sm"><span className="text-slate-400">{k}</span><span className="text-white">{v}</span></div>)}</div>
      <Toggle id="subtitles-toggle" label="Burned-in Gujarati subtitles" checked={p.subtitle_style.enabled} onChange={(v) => set({ subtitle_style: { ...p.subtitle_style, enabled: v } })} hint="SRT and WebVTT exports are always available" />
      <Toggle id="branding-toggle" label="Channel branding" checked={p.branding.branding_enabled} onChange={(v) => set({ branding: { ...p.branding, branding_enabled: v } })} />
      <p className="rounded-md border border-blue-500/30 bg-blue-500/5 p-3 text-xs text-blue-200">The talking anchor is generated at the provider's native resolution, then composed onto a 1920×1080 broadcast canvas by our renderer.</p>
    </div>
  );
}

function StepBranding({ p, set, onRenderFrame }) {
  const b = p.branding; const sb = (k) => (v) => set({ branding: { ...b, [k]: v } });
  const s = p.subtitle_style; const ss = (k) => (v) => set({ subtitle_style: { ...s, [k]: v } });
  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <div><Label className="text-xs text-slate-400">Channel name</Label><Input data-testid="branding-channel-name-input" value={b.channel_name} onChange={(e) => sb("channel_name")(e.target.value)} className="gu mt-1 bg-[#0B0F19]" /></div>
        <div><Label className="text-xs text-slate-400">Banner text</Label><Input data-testid="branding-banner-input" value={b.banner_text} onChange={(e) => sb("banner_text")(e.target.value)} className="mt-1 bg-[#0B0F19]" /></div>
        <ColorField id="branding-primary" label="Primary colour" value={b.primary_color} onChange={sb("primary_color")} />
        <ColorField id="branding-secondary" label="Secondary colour" value={b.secondary_color} onChange={sb("secondary_color")} />
      </div>
      <div className="flex gap-2">{["top-left", "top-right"].map((k) => <Button key={k} size="sm" variant="outline" data-testid={`branding-logo-corner-${k}`} onClick={() => sb("logo_corner")(k)} className={`bg-transparent ${b.logo_corner === k ? "border-red-500" : "border-[#374151] text-slate-400"}`}>Logo {k}</Button>)}
        <span className="self-center text-xs text-slate-500">Logo comes from the selected channel preset.</span></div>
      <Toggle id="ticker-toggle" label="Scrolling ticker" checked={b.ticker_enabled} onChange={sb("ticker_enabled")} />
      {b.ticker_enabled && <div className="grid gap-3 sm:grid-cols-3"><Input data-testid="ticker-label-input" value={b.ticker_label} onChange={(e) => sb("ticker_label")(e.target.value)} className="gu bg-[#0B0F19]" />
        <Textarea data-testid="ticker-text-input" rows={2} value={b.ticker_text} onChange={(e) => sb("ticker_text")(e.target.value)} placeholder="One ticker item per line" className="gu bg-[#0B0F19] sm:col-span-2" /></div>}
      <div className="rounded-lg border border-[#263346] p-4">
        <div className="text-sm font-semibold text-white">Subtitle style</div>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <div><Label className="text-xs text-slate-400">Size: {s.size}px</Label><Slider data-testid="subtitle-size-slider" min={28} max={64} step={2} value={[s.size]} onValueChange={([v]) => ss("size")(v)} className="mt-3" /></div>
          <ColorField id="subtitle" label="Text colour" value={s.color} onChange={ss("color")} />
          <div className="flex gap-2">{["box", "outline"].map((k) => <Button key={k} size="sm" variant="outline" data-testid={`subtitle-bg-${k}`} onClick={() => ss("background")(k)} className={`bg-transparent capitalize ${s.background === k ? "border-red-500" : "border-[#374151] text-slate-400"}`}>{k}</Button>)}</div>
          <div className="flex gap-2">{["bottom", "top"].map((k) => <Button key={k} size="sm" variant="outline" data-testid={`subtitle-pos-${k}`} onClick={() => ss("position")(k)} className={`bg-transparent capitalize ${s.position === k ? "border-red-500" : "border-[#374151] text-slate-400"}`}>{k}</Button>)}</div>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <Toggle id="intro-toggle" label="Intro card (3s)" checked={b.intro_enabled} onChange={sb("intro_enabled")} />
        <Toggle id="outro-toggle" label="Outro card (3s)" checked={b.outro_enabled} onChange={sb("outro_enabled")} />
        <Toggle id="date-toggle" label="Gujarati date" checked={b.show_date} onChange={sb("show_date")} />
      </div>
      <Button variant="outline" data-testid="render-exact-frame-btn" onClick={onRenderFrame} className="border-[#374151] bg-transparent"><ImageIcon /> Render exact frame with the video renderer</Button>
    </div>
  );
}

function StepGenerate({ p, analysis, anchor, consent, setConsent, verified }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="card-surface p-4"><div className="eyebrow">Estimated charge</div><div className="mt-2 text-2xl font-bold text-white" data-testid="estimated-credits">{analysis?.estimated_credits ?? 0} credits</div><div className="text-xs text-slate-400">≈ {analysis?.estimated_seconds}s narration · min 10</div></div>
        <div className="card-surface p-4"><div className="eyebrow">Reserved at submit</div><div className="mt-2 text-2xl font-bold text-amber-300" data-testid="reserve-credits">{analysis?.reserve_credits ?? 0}</div><div className="text-xs text-slate-400">+15% buffer, unused part released</div></div>
        <div className="card-surface p-4"><div className="eyebrow">Processing time</div><div className="mt-2 text-2xl font-bold text-white">~3–10 min</div><div className="text-xs text-slate-400">Narration → anchor → render</div></div>
      </div>
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-slate-300">
        <p>This creates a <b>synthetic</b> video of <b>{anchor?.display_name || "the selected anchor"}</b> speaking your script. The video will display “AI દ્વારા બનાવાયેલ પ્રસ્તુતકર્તા વિડિયો / AI-generated presenter video” for its full length. Do not present it as real on-location footage or as statements the person actually made.</p>
        <label className="mt-3 flex items-start gap-2"><Checkbox data-testid="generate-consent-checkbox" checked={consent} onCheckedChange={(v) => setConsent(!!v)} className="mt-0.5" /> I have permission to animate this person's image and to use the generated likeness and voice for this video.</label>
      </div>
      {!verified && <p className="text-sm text-amber-300" data-testid="verify-required-msg">Verify your email address before generating.</p>}
      {!analysis?.valid && <p className="text-sm text-red-300">Fix the script issues in step 2 before generating.</p>}
      <p className="text-xs text-slate-500">Credits are released in full if the job fails or is cancelled. Final charge = actual narration seconds (rounded up, minimum 10).</p>
    </div>
  );
}

export default function Creator() {
  const { projectId } = useParams();
  const nav = useNavigate();
  const { user } = useAuth();
  const [p, setP] = useState(BLANK);
  const [step, setStep] = useState(0);
  const [analysis, setAnalysis] = useState(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [frame, setFrame] = useState(null);
  const idem = useRef(newKey());
  const { data: anchors } = useSWR("/anchors", fetcher);
  const { data: channels } = useSWR("/channels", fetcher);

  useEffect(() => {
    if (!projectId) { setP(BLANK); setStep(0); return; }
    api.get(`/projects/${projectId}`).then(({ data }) => { setP(data); setAnalysis(data.analysis); }).catch((e) => toast.error(errMsg(e)));
  }, [projectId]);

  useEffect(() => {
    const t = setTimeout(() => api.post("/scripts/analyze", { script: p.script, pronunciation: p.pronunciation.filter((x) => x.word && x.say) }).then(({ data }) => setAnalysis(data)).catch(() => {}), 350);
    return () => clearTimeout(t);
  }, [p.script, p.pronunciation]);

  const set = (patch) => setP((x) => ({ ...x, ...patch }));
  const anchor = (anchors?.items || []).find((a) => a.id === p.anchor_id);
  const channel = (channels?.items || []).find((c) => c.id === p.channel_id);
  const firstCue = useMemo(() => (p.script || "").split(/(?<=[।.!?])\s+|\n+/)[0]?.slice(0, 90), [p.script]);
  const locked = p.status && ["queued", "validating", "generating", "retrieving", "rendering"].includes(p.status);

  const save = async (quiet) => {
    const body = Object.fromEntries(PAYLOAD.map((k) => [k, p[k]]));
    body.pronunciation = (body.pronunciation || []).filter((x) => x.word && x.say);
    try {
      if (p.id) { const { data } = await api.patch(`/projects/${p.id}`, body); setP(data); }
      else { const { data } = await api.post("/projects", body); setP(data); nav(`/app/new/${data.id}`, { replace: true }); }
      if (!quiet) toast.success("Draft saved");
      return true;
    } catch (e) { toast.error(errMsg(e)); return false; }
  };
  const go = async (i) => { if (!locked && !(await save(true))) return; setStep(i); };
  const generate = async () => {
    if (!(await save(true))) return;
    setBusy(true);
    try {
      const id = p.id || window.location.pathname.split("/").pop();
      await api.post(`/projects/${id}/generate`, { consent_confirmed: true }, { headers: { "Idempotency-Key": idem.current } });
      toast.success("Job submitted. Tracking progress on the Jobs page.");
      nav("/app/jobs");
    } catch (e) { toast.error(errMsg(e)); idem.current = newKey(); } finally { setBusy(false); }
  };
  const renderFrame = async () => {
    try {
      const { data } = await api.post("/compose/preview-frame", { anchor_id: p.anchor_id, channel_id: p.channel_id, headline: p.headline, location: p.location, sample_subtitle: firstCue || "", branding: p.branding, subtitle_style: p.subtitle_style }, { responseType: "blob" });
      setFrame(URL.createObjectURL(data));
    } catch (e) { toast.error("Could not render the preview frame"); }
  };
  const canNext = [!!p.anchor_id, !!analysis?.valid, !!p.voice, true, true, true][step] ?? true;
  const Body = [StepAnchor, StepScript, StepVoice, StepTemplate, StepSettings, StepBranding][step];

  return (
    <div className="space-y-6 fade-up">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><div className="eyebrow">News video creator</div><h1 className="mt-1 text-3xl font-bold text-white">{p.name}</h1></div>
        {!locked && <Button variant="outline" data-testid="save-draft-btn" onClick={() => save(false)} className="border-[#374151] bg-transparent"><Save /> Save draft</Button>}
      </div>
      {locked && <p className="rounded-md border border-blue-500/30 bg-blue-500/5 p-3 text-sm text-blue-200" data-testid="project-locked-msg">This project is generating. Settings are locked until the job finishes.</p>}
      <ol className="flex gap-1 overflow-x-auto" data-testid="wizard-step-rail">
        {STEPS.map((s, i) => (
          <li key={s}><button data-testid={`wizard-step-${i + 1}-tab`} onClick={() => go(i)} className={`flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-xs font-semibold ${i === step ? "bg-red-600 text-white" : i < step ? "bg-[#182232] text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>
            <span className="mono">{i + 1}</span>{s}</button></li>))}
      </ol>
      <div className="grid gap-6 xl:grid-cols-12">
        <div className="card-surface p-5 sm:p-6 xl:col-span-7">
          {step < 6 ? <Body p={p} set={set} analysis={analysis} anchors={anchors?.items || []} channels={channels?.items || []} onRenderFrame={renderFrame} />
            : <StepGenerate p={p} analysis={analysis} anchor={anchor} consent={consent} setConsent={setConsent} verified={user?.email_verified} />}
          <div className="mt-8 flex justify-between border-t border-[#263346] pt-5">
            <Button variant="ghost" data-testid="wizard-back-btn" disabled={step === 0} onClick={() => go(step - 1)}>Back</Button>
            {step < 6 ? <Button data-testid={`wizard-step-${step + 1}-next-button`} disabled={!canNext} onClick={() => go(step + 1)} className="bg-red-600 hover:bg-red-700">Next</Button>
              : <Button data-testid="generate-video-btn" disabled={busy || locked || !consent || !analysis?.valid || !p.anchor_id || !user?.email_verified} onClick={generate} className="bg-red-600 hover:bg-red-700">{busy ? "Submitting…" : `Generate 16:9 video · ~${analysis?.estimated_credits ?? 0} credits`}</Button>}
          </div>
        </div>
        <div className="xl:col-span-5"><div className="sticky top-20 space-y-2">
          <CompositionPreview portraitUrl={anchor?.image_url} logoUrl={p.branding.branding_enabled ? channel?.logo_url : null} branding={p.branding} headline={p.headline} location={p.location} subtitle={firstCue} subtitleStyle={p.subtitle_style} />
          <p className="text-xs text-slate-500">Uses your real portrait and text. The final video replaces the still portrait with the AI-generated talking anchor.</p>
        </div></div>
      </div>
      <Dialog open={!!frame} onOpenChange={() => setFrame(null)}>
        <DialogContent className="max-w-5xl border-[#263346] bg-[#111827]"><DialogHeader><DialogTitle>Renderer frame · static preview, not the generated video</DialogTitle></DialogHeader>
          {frame && <img data-testid="rendered-frame-img" src={frame} alt="Rendered composition preview" className="w-full rounded" />}</DialogContent>
      </Dialog>
    </div>
  );
}
