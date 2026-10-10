const cq = (px) => `${(px / 1920) * 100}cqw`;
const DISCLOSURE = "AI દ્વારા બનાવાયેલ પ્રસ્તુતકર્તા વિડિયો · AI-generated presenter video";

export default function CompositionPreview({ portraitUrl, logoUrl, branding = {}, headline, location, subtitle, subtitleStyle = {}, testId = "composition-preview" }) {
  const b = branding;
  const primary = b.primary_color || "#DC2626";
  const secondary = b.secondary_color || "#0F172A";
  const right = (b.logo_corner || "top-right") === "top-right";
  const sub = subtitleStyle;
  const subSize = sub.size || 42;
  const ticker = (b.ticker_text || "").split("\n").filter(Boolean).join("   •   ");
  const today = new Date().toLocaleDateString("gu-IN", { day: "numeric", month: "long", year: "numeric" });
  return (
    <div data-testid={testId} className="relative w-full overflow-hidden rounded-lg border border-[#263346] gu"
      style={{ aspectRatio: "16/9", containerType: "inline-size", background: `radial-gradient(ellipse at 50% 40%, ${secondary} 0%, #0B0F19 70%)` }}>
      <div className="absolute inset-0 opacity-30" style={{ backgroundImage: "linear-gradient(90deg, #182232 1px, transparent 1px)", backgroundSize: "6.25% 100%" }} />
      {portraitUrl && <img src={portraitUrl} alt="Anchor portrait" className="absolute left-1/2 top-[2.8%] h-[83%] -translate-x-1/2 object-contain" />}
      {b.branding_enabled !== false && (logoUrl
        ? <img src={logoUrl} alt="Channel logo" className="absolute top-[5%] max-h-[11%] max-w-[11.5%] object-contain" style={right ? { right: "5%" } : { left: "5%" }} />
        : b.channel_name && <div className="absolute top-[5%] rounded font-bold text-white" style={{ ...(right ? { right: "5%" } : { left: "5%" }), background: primary, fontSize: cq(36), padding: `${cq(8)} ${cq(20)}` }}>{b.channel_name}</div>)}
      <div className="absolute top-[5%] rounded-full border border-white/30 bg-black/70 text-white" style={{ ...(right ? { left: "5%" } : { right: "5%" }), fontSize: cq(22), padding: `${cq(8)} ${cq(18)}` }}>{DISCLOSURE}</div>
      {sub.enabled !== false && subtitle && (
        <div className="absolute left-1/2 max-w-[80%] -translate-x-1/2 rounded-md text-center font-semibold"
          style={{ [sub.position === "top" ? "top" : "bottom"]: sub.position === "top" ? "11%" : "26.9%", fontSize: cq(subSize), color: sub.color || "#fff",
            padding: `${cq(10)} ${cq(26)}`, background: (sub.background || "box") === "box" ? "rgba(0,0,0,.68)" : "transparent",
            textShadow: sub.background === "outline" ? "0 0 4px #000, 0 0 4px #000, 0 0 6px #000" : "none", lineHeight: 1.5 }}>{subtitle}</div>)}
      <div className="absolute left-[5%] right-[5%] top-[74.07%]">
        <div className="flex" style={{ height: cq(58) }}>
          <div className="flex items-center font-extrabold text-white" style={{ background: primary, fontSize: cq(32), padding: `0 ${cq(24)}` }}>{(b.banner_text || "BREAKING NEWS").toUpperCase()}</div>
          {location && <div className="flex items-center bg-white font-semibold text-slate-900" style={{ fontSize: cq(27), padding: `0 ${cq(22)}` }}>{location}</div>}
          {b.show_date && <div className="flex items-center bg-slate-900/90 text-slate-200" style={{ fontSize: cq(25), padding: `0 ${cq(20)}` }}>{today}</div>}
        </div>
        <div className="flex items-center overflow-hidden whitespace-nowrap font-bold text-white" style={{ height: cq(90), background: secondary, borderLeft: `${cq(10)} solid ${primary}`, fontSize: cq(46), paddingLeft: cq(26) }}>{headline || <span className="opacity-40">મુખ્ય હેડલાઇન અહીં દેખાશે</span>}</div>
      </div>
      <div className="absolute left-0 right-0 top-[89.8%] flex overflow-hidden border-t-2 border-red-500 bg-[#090C14]" style={{ height: cq(56) }}>
        <div className="z-10 flex shrink-0 items-center font-extrabold text-white" style={{ background: primary, fontSize: cq(27), paddingLeft: "5%", paddingRight: cq(24) }}>{b.ticker_label || "તાજા સમાચાર"}</div>
        {b.ticker_enabled !== false && ticker && (
          <div className="flex items-center whitespace-nowrap text-white" style={{ fontSize: cq(29) }}>
            <div className="ticker-run flex">{[0, 1].map((k) => <span key={k} className="pl-[2cqw]">{ticker}   •   </span>)}</div>
          </div>)}
      </div>
      <div data-testid="static-preview-label" className="absolute bottom-[1%] right-[1%] rounded bg-amber-500/90 px-1.5 py-0.5 font-sans text-[10px] font-bold uppercase tracking-wider text-black">Static preview · not the generated video</div>
    </div>
  );
}
