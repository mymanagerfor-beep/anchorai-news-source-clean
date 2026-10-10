import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { AlertTriangle, Copy, Smartphone } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

function UpiDialog({ pack, upi, onClose, onDone }) {
  const [ref, setRef] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  if (!pack) return null;
  const link = `upi://pay?pa=${encodeURIComponent(upi.upi_id)}&pn=${encodeURIComponent(upi.payee_name)}&am=${pack.price_inr.toFixed(2)}&cu=INR&tn=${encodeURIComponent(`AnchorAI ${pack.name} pack`)}`;
  const submit = async () => {
    setBusy(true);
    try { await api.post("/billing/upi/submit", { pack_id: pack.id, upi_ref: ref.trim(), payer_name: name }); toast.success("Payment submitted. Credits are added after the admin confirms receipt."); onDone(); onClose(); }
    catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-h-[92vh] max-w-lg overflow-y-auto border-[#263346] bg-[#111827]" data-testid="upi-dialog">
        <DialogHeader><DialogTitle>Pay ₹{pack.price_inr.toLocaleString("en-IN")} via UPI · {pack.name} ({pack.credits} credits)</DialogTitle></DialogHeader>
        <img src={upi.qr_image} alt="UPI QR code" data-testid="upi-qr-image" className="mx-auto w-64 rounded-lg" />
        <div className="flex items-center justify-between rounded-md border border-[#263346] bg-[#0B0F19] px-3 py-2 text-sm">
          <div><div className="text-xs text-slate-500">UPI ID · {upi.payee_name}</div><div className="mono text-white" data-testid="upi-id-text">{upi.upi_id}</div></div>
          <Button size="sm" variant="ghost" data-testid="upi-copy-btn" onClick={() => { navigator.clipboard.writeText(upi.upi_id); toast.success("UPI ID copied"); }}><Copy /></Button>
        </div>
        <a href={link} data-testid="upi-app-link" className="flex items-center justify-center gap-2 rounded-md border border-[#374151] py-2 text-sm text-slate-200 sm:hidden"><Smartphone className="h-4 w-4" /> Open UPI app</a>
        <ol className="list-decimal space-y-1 pl-5 text-xs text-slate-400">
          <li>Scan the QR or pay to the UPI ID the exact amount <b className="text-white">₹{pack.price_inr.toLocaleString("en-IN")}</b>.</li>
          <li>Copy the 12-digit UPI reference / UTR number from your payment app.</li>
          <li>Submit it below. Credits are added once the payment is confirmed by the admin.</li>
        </ol>
        <div className="space-y-3">
          <div><Label className="text-xs">UPI reference / UTR number</Label><Input data-testid="upi-ref-input" value={ref} onChange={(e) => setRef(e.target.value.replace(/[^A-Za-z0-9]/g, ""))} placeholder="e.g. 412345678901" className="mono mt-1 bg-[#0B0F19]" /></div>
          <div><Label className="text-xs">Payer name (optional)</Label><Input data-testid="upi-payer-input" value={name} onChange={(e) => setName(e.target.value)} className="mt-1 bg-[#0B0F19]" /></div>
          <Button data-testid="upi-submit-btn" disabled={busy || ref.trim().length < 6} onClick={submit} className="w-full bg-red-600 hover:bg-red-700">{busy ? "Submitting…" : "I have paid — submit reference"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
import { api, fetcher, errMsg, fmtDate } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { TxTable } from "@/pages/Dashboard";

export default function Billing() {
  const { data: bal, mutate: mBal } = useSWR("/billing/balance", fetcher);
  const { data: packs } = useSWR("/billing/packs", fetcher);
  const { data: ledger, mutate: mLed } = useSWR("/billing/ledger", fetcher);
  const { data: pays, mutate: mPay } = useSWR("/billing/payments", fetcher);
  const [busy, setBusy] = useState(null);
  const [upiPack, setUpiPack] = useState(null);
  const refresh = () => { mBal(); mLed(); mPay(); };

  const buy = async (pack) => {
    setBusy(pack.id);
    try {
      const { data: o } = await api.post("/billing/checkout", { pack_id: pack.id });
      if (!window.Razorpay) throw new Error("Payment window failed to load. Check your connection and retry.");
      const rz = new window.Razorpay({
        key: o.key_id, order_id: o.order_id, amount: o.amount, currency: o.currency, name: o.name, description: o.description, prefill: o.prefill, theme: { color: "#DC2626" },
        handler: async (resp) => {
          try { const { data } = await api.post("/billing/verify", resp); data.status === "paid" ? toast.success("Payment verified. Credits added.") : toast.message(data.message); }
          catch (e) { toast.error(errMsg(e)); } finally { refresh(); }
        },
        modal: { ondismiss: () => setBusy(null) },
      });
      rz.on("payment.failed", (r) => toast.error(r.error?.description || "Payment failed"));
      rz.open();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(null); }
  };

  return (
    <div className="space-y-8 fade-up">
      <div><div className="eyebrow">Credits ledger</div><h1 className="mt-1 text-3xl font-bold text-white">Billing & credits</h1></div>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="card-surface p-5"><div className="eyebrow">Available</div><div className="mt-2 font-display text-4xl font-bold text-white" data-testid="billing-available">{bal?.unlimited ? "∞ Unlimited" : bal?.available ?? "—"}</div>{bal?.unlimited && <div className="mt-1 text-xs text-emerald-300">Admin workspace: generations are never charged</div>}</div>
        <div className="card-surface p-5"><div className="eyebrow">Held for running jobs</div><div className="mt-2 font-display text-4xl font-bold text-amber-300" data-testid="billing-reserved">{bal?.reserved ?? "—"}</div></div>
        <div className="card-surface p-5 text-sm text-slate-400"><div className="eyebrow">Pricing policy</div><p className="mt-2">{packs?.pricing_note}</p><p className="mt-1">Failed or cancelled jobs release all reserved credits.</p></div>
      </div>
      {packs && !packs.payments_configured && !packs.manual_upi?.enabled && <div data-testid="payments-not-configured" className="flex items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200"><AlertTriangle className="h-4 w-4" /> Online payments are not configured yet. The administrator must add Razorpay keys before packs can be purchased.</div>}
      <div className="grid gap-4 md:grid-cols-3">
        {(packs?.packs || []).map((p) => (
          <div key={p.id} className="card-surface p-6" data-testid={`pack-card-${p.id}`}>
            <div className="eyebrow">{p.name}</div><div className="mt-2 text-3xl font-bold text-white">₹{p.price_inr.toLocaleString("en-IN")}</div>
            <div className="text-sm text-slate-400">{p.credits} credits · ₹{(p.price_inr / p.credits).toFixed(2)}/credit</div>
            {packs.manual_upi?.enabled && <Button data-testid={`upi-pay-btn-${p.id}`} onClick={() => setUpiPack(p)} className="mt-5 w-full bg-red-600 hover:bg-red-700">Pay via UPI (QR)</Button>}
            {packs.payments_configured && <Button data-testid={`buy-pack-btn-${p.id}`} disabled={busy === p.id} onClick={() => buy(p)} variant="outline" className="mt-2 w-full border-[#374151] bg-transparent">{busy === p.id ? "Opening…" : "Pay with Razorpay"}</Button>}
          </div>))}
      </div>
      {upiPack && <UpiDialog pack={upiPack} upi={packs.manual_upi} onClose={() => setUpiPack(null)} onDone={refresh} />}
      <div className="grid gap-6 lg:grid-cols-12">
        <div className="card-surface p-5 lg:col-span-7"><h3 className="font-semibold text-white">Usage & transaction ledger</h3><p className="text-xs text-slate-500">Append-only. Reservation, capture and release entries are linked to jobs.</p><div className="mt-3 max-h-[480px] overflow-y-auto"><TxTable items={ledger?.items || []} /></div></div>
        <div className="card-surface p-5 lg:col-span-5"><h3 className="font-semibold text-white">Payments & receipts</h3>
          <div className="mt-3 space-y-2 text-sm">
            {(pays?.items || []).map((p) => (
              <div key={p.id} className="flex items-center justify-between rounded border border-[#263346] p-3" data-testid={`payment-row-${p.id}`}>
                <div><div className="text-white">{p.credits} credits · ₹{p.amount}</div><div className="mono text-[11px] text-slate-500">{p.provider === "upi_manual" ? `UPI ref ${p.upi_ref}` : `${p.order_id} ${p.payment_id ? `· ${p.payment_id}` : ""}`}</div>{p.review_note && <div className="text-xs text-slate-400">{p.review_note}</div>}<div className="text-xs text-slate-500">{fmtDate(p.created_at)}</div></div>
                <span className={`text-xs font-semibold capitalize ${p.status === "paid" ? "text-emerald-300" : ["failed", "rejected"].includes(p.status) ? "text-red-300" : "text-amber-300"}`}>{p.status.replace("_", " ")}</span>
              </div>))}
            {pays && !pays.items.length && <p className="py-6 text-center text-slate-500">No payments yet.</p>}
          </div>
          <p className="mt-3 text-xs text-slate-500">UPI payments are confirmed manually, usually within a few hours. Razorpay emails a receipt for each payment. Card refunds are processed manually by the administrator.</p>
        </div>
      </div>
    </div>
  );
}
