import { Link } from "react-router-dom";
import useSWR from "swr";
import { Mic, Captions, Radio, ShieldCheck, Upload, FileText, Palette, Download, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fetcher } from "@/lib/api";
import { Logo } from "@/components/AppLayout";
import CompositionPreview from "@/components/CompositionPreview";

const FEATURES = [
  [Mic, "Real Gujarati narration", "ElevenLabs v3 voices with the language locked to Gujarati. No silent fallback to Hindi or English."],
  [Radio, "Lip-synced talking anchor", "Kling AI Avatar v2 animates your authorized portrait to the narration."],
  [Captions, "Timed Gujarati subtitles", "Burned-in captions timed from the narration's character timestamps, plus SRT and WebVTT export."],
  [ShieldCheck, "Consent and disclosure built in", "Versioned consent records, revocation, and a visible AI-generated label on every frame."],
];
const STEPS = [[Upload, "Upload an authorized portrait"], [FileText, "Write your Gujarati script"], [Palette, "Brand the Breaking News frame"], [Download, "Download a 1080p MP4"]];

export default function Landing() {
  const { data } = useSWR("/billing/packs", fetcher);
  return (
    <div className="min-h-screen bg-[#0B0F19] text-white">
      <header className="sticky top-0 z-50 flex items-center justify-between border-b border-[#263346] bg-[#0B0F19]/90 px-6 py-4 backdrop-blur-xl lg:px-12">
        <Logo />
        <div className="flex items-center gap-3">
          <Link to="/login"><Button data-testid="landing-signin-btn" variant="ghost" className="text-slate-300">Sign in</Button></Link>
          <Link to="/signup"><Button data-testid="landing-signup-btn" className="bg-red-600 hover:bg-red-700">Start free trial</Button></Link>
        </div>
      </header>

      <section className="grid gap-12 px-6 pb-20 pt-16 lg:grid-cols-12 lg:px-12 lg:pt-24">
        <div className="fade-up lg:col-span-6">
          <div className="inline-flex items-center gap-2 rounded-full border border-red-500/30 bg-red-500/10 px-3 py-1 text-xs font-semibold text-red-300"><span className="live-dot" /> Gujarati AI news-anchor studio</div>
          <h1 className="mt-6 text-4xl font-bold leading-[1.05] tracking-tight sm:text-5xl lg:text-6xl">Turn a Gujarati script into a <span className="text-red-500">Breaking News</span> bulletin.</h1>
          <p className="gu mt-6 text-lg text-slate-300">તમારી ગુજરાતી સ્ક્રિપ્ટ, તમારો અધિકૃત એન્કર, તમારું ચેનલ બ્રાન્ડિંગ.</p>
          <p className="mt-3 max-w-xl text-base text-slate-400">Upload an authorized presenter portrait, write the news in Gujarati, and get a lip-synced, branded 1920×1080 MP4 with subtitles, a scrolling ticker and a visible AI-generated disclosure.</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/signup"><Button data-testid="hero-cta-btn" size="lg" className="bg-red-600 hover:bg-red-700">Start the 16:9 studio</Button></Link>
            <a href="#pricing"><Button data-testid="hero-pricing-btn" size="lg" variant="outline" className="border-[#374151] bg-transparent">See pricing</Button></a>
          </div>
          <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-slate-400">
            {["Gujarati (gu-IN)", "16:9 · 1920×1080", "MP4 · H.264 + AAC", "SRT / WebVTT"].map((t) => <span key={t} className="flex items-center gap-1.5"><Check className="h-4 w-4 text-emerald-400" />{t}</span>)}
          </div>
        </div>
        <div className="fade-up lg:col-span-6" style={{ animationDelay: ".15s" }}>
          <CompositionPreview testId="landing-composition-mockup" headline="અમદાવાદમાં ભારે વરસાદ, શાળાઓમાં રજા" location="અમદાવાદ" subtitle="આજે સવારથી શહેરમાં સતત વરસાદ પડી રહ્યો છે."
            branding={{ channel_name: "તમારી ચેનલ", ticker_text: "રાજ્યમાં ચોમાસું સક્રિય\nસરદાર સરોવર ડેમની સપાટી વધી", show_date: true }} />
          <p className="mt-3 text-xs text-slate-500">Layout mockup of the Breaking News template. The anchor area is filled by your own AI-generated presenter video. No sample videos are shown.</p>
        </div>
      </section>

      <section className="border-y border-[#263346] bg-[#0D1220] px-6 py-16 lg:px-12">
        <div className="eyebrow">Workflow</div>
        <div className="mt-6 grid gap-4 md:grid-cols-4">
          {STEPS.map(([Icon, t], i) => (
            <div key={t} className="card-surface p-5"><div className="mono text-xs text-red-400">0{i + 1}</div><Icon className="mt-3 h-5 w-5 text-slate-300" /><div className="mt-3 font-semibold">{t}</div></div>
          ))}
        </div>
      </section>

      <section className="px-6 py-20 lg:px-12">
        <h2 className="text-2xl font-bold sm:text-3xl">Built for regional newsrooms</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-2">
          {FEATURES.map(([Icon, t, d]) => (
            <div key={t} className="card-surface flex gap-4 p-6 transition-colors hover:border-[#374151]"><Icon className="h-6 w-6 shrink-0 text-red-400" /><div><div className="font-semibold">{t}</div><p className="mt-1 text-sm text-slate-400">{d}</p></div></div>
          ))}
        </div>
      </section>

      <section id="pricing" className="border-t border-[#263346] px-6 py-20 lg:px-12">
        <h2 className="text-2xl font-bold sm:text-3xl">Credit packs</h2>
        <p className="mt-2 text-sm text-slate-400">1 credit = 1 second of finished narration (minimum 10 per video). One-time packs in INR, no subscription. New workspaces get 30 trial credits after email verification.</p>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {(data?.packs || []).map((p, i) => (
            <div key={p.id} data-testid={`landing-pack-${p.id}`} className={`card-surface p-6 ${i === 1 ? "border-red-500/60" : ""}`}>
              <div className="eyebrow">{p.name}</div>
              <div className="mt-3 text-3xl font-bold">₹{p.price_inr.toLocaleString("en-IN")}</div>
              <div className="mt-1 text-sm text-slate-400">{p.credits} credits · ≈ {Math.floor(p.credits / 60)} min of bulletins</div>
              <ul className="mt-5 space-y-2 text-sm text-slate-300">
                <li>1920×1080 MP4 (H.264/AAC)</li><li>Gujarati subtitles + SRT/VTT</li><li>Credits never expire</li>
              </ul>
            </div>))}
        </div>
      </section>

      <section className="px-6 pb-20 lg:px-12">
        <div className="card-surface border-amber-500/30 p-6 text-sm text-slate-300" data-testid="ai-disclosure-section">
          <div className="font-semibold text-amber-300">Synthetic media disclosure</div>
          <p className="mt-2">Presenters and videos produced with AnchorAI News are AI-generated. Every video carries the label <span className="gu text-white">“AI દ્વારા બનાવાયેલ પ્રસ્તુતકર્તા વિડિયો”</span> / “AI-generated presenter video”. You may only animate people who have authorized it, and you may not use generated anchors to suggest someone was present at an event or made statements they did not make.</p>
        </div>
      </section>
      <footer className="border-t border-[#263346] px-6 py-8 text-xs text-slate-500 lg:px-12">© {new Date().getFullYear()} AnchorAI News · Gujarati (gu-IN) · 16:9 1080p MP4 · AI-generated presenter videos</footer>
    </div>
  );
}
