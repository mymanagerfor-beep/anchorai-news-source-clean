import { useState, useEffect, useRef } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Logo } from "@/components/AppLayout";

const Shell = ({ title, sub, children }) => (
  <div className="flex min-h-screen items-center justify-center bg-[#0B0F19] px-4">
    <div className="w-full max-w-md fade-up">
      <Link to="/" className="mb-8 inline-block"><Logo /></Link>
      <div className="card-surface p-7">
        <h1 className="text-2xl font-bold text-white">{title}</h1>
        {sub && <p className="mt-1 text-sm text-slate-400">{sub}</p>}
        <div className="mt-6">{children}</div>
      </div>
    </div>
  </div>
);

const Field = ({ id, label, ...p }) => (
  <div className="space-y-1.5">
    <Label htmlFor={id} className="text-slate-300">{label}</Label>
    <Input id={id} data-testid={`${id}-input`} className="bg-[#111827]" {...p} />
  </div>
);

function useForm(init) {
  const [f, setF] = useState(init);
  return [f, (k) => (e) => setF({ ...f, [k]: e.target.value })];
}

export function Login() {
  const [f, on] = useForm({ email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const { signIn } = useAuth();
  const nav = useNavigate();
  const [qs] = useSearchParams();
  const submit = async (e) => {
    e.preventDefault(); setBusy(true);
    try { const { data } = await api.post("/auth/login", f); signIn(data); nav("/app"); }
    catch (err) { toast.error(errMsg(err)); } finally { setBusy(false); }
  };
  return (
    <Shell title="Sign in" sub={qs.get("expired") ? "Your session expired. Please sign in again." : "Welcome back to the newsroom."}>
      <form onSubmit={submit} className="space-y-4">
        <Field id="login-email" label="Email" type="email" required value={f.email} onChange={on("email")} />
        <Field id="login-password" label="Password" type="password" required value={f.password} onChange={on("password")} />
        <Button data-testid="login-submit-btn" disabled={busy} className="w-full bg-red-600 hover:bg-red-700">{busy ? "Signing in…" : "Sign in"}</Button>
      </form>
      <div className="mt-5 flex justify-between text-sm text-slate-400">
        <Link data-testid="forgot-password-link" to="/forgot-password" className="hover:text-white">Forgot password?</Link>
        <Link data-testid="signup-link" to="/signup" className="hover:text-white">Create account</Link>
      </div>
    </Shell>
  );
}

export function Signup() {
  const [f, on] = useForm({ name: "", email: "", password: "", workspace_name: "" });
  const [busy, setBusy] = useState(false);
  const { signIn } = useAuth();
  const nav = useNavigate();
  const submit = async (e) => {
    e.preventDefault(); setBusy(true);
    try {
      const { data } = await api.post("/auth/register", f);
      signIn(data);
      toast.success(data.verification_email_sent ? "Account created. Check your inbox to verify your email." : "Account created. Verification email could not be sent — use Resend from the banner.");
      nav("/app");
    } catch (err) { toast.error(errMsg(err)); } finally { setBusy(false); }
  };
  return (
    <Shell title="Create your newsroom" sub="A workspace is created for you. 30 trial credits unlock after email verification.">
      <form onSubmit={submit} className="space-y-4">
        <Field id="signup-name" label="Your name" required value={f.name} onChange={on("name")} />
        <Field id="signup-workspace" label="Workspace / channel group name" required value={f.workspace_name} onChange={on("workspace_name")} placeholder="e.g. Saurashtra Samachar Digital" />
        <Field id="signup-email" label="Work email" type="email" required value={f.email} onChange={on("email")} />
        <Field id="signup-password" label="Password (min 8 characters)" type="password" minLength={8} required value={f.password} onChange={on("password")} />
        <Button data-testid="signup-submit-btn" disabled={busy} className="w-full bg-red-600 hover:bg-red-700">{busy ? "Creating…" : "Create account"}</Button>
      </form>
      <p className="mt-4 text-xs text-slate-500">Videos made with AnchorAI News feature AI-generated presenters and must carry the visible AI disclosure.</p>
      <div className="mt-4 text-sm text-slate-400">Already have an account? <Link data-testid="login-link" to="/login" className="text-white underline-offset-4 hover:underline">Sign in</Link></div>
    </Shell>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    try { await api.post("/auth/forgot-password", { email }); setDone(true); } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Shell title="Reset password" sub="We'll email you a single-use reset link valid for 1 hour.">
      {done ? <p data-testid="forgot-done-msg" className="text-sm text-emerald-300">If an account exists for this email, a reset link has been sent.</p> : (
        <form onSubmit={submit} className="space-y-4">
          <Field id="forgot-email" label="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <Button data-testid="forgot-submit-btn" className="w-full bg-red-600 hover:bg-red-700">Send reset link</Button>
        </form>)}
      <Link to="/login" className="mt-4 inline-block text-sm text-slate-400 hover:text-white">Back to sign in</Link>
    </Shell>
  );
}

export function ResetPassword() {
  const [qs] = useSearchParams();
  const [pw, setPw] = useState("");
  const nav = useNavigate();
  const submit = async (e) => {
    e.preventDefault();
    try { await api.post("/auth/reset-password", { token: qs.get("token"), password: pw }); toast.success("Password updated. Sign in with your new password."); nav("/login"); }
    catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <Shell title="Choose a new password" sub="All existing sessions will be signed out.">
      <form onSubmit={submit} className="space-y-4">
        <Field id="reset-password" label="New password" type="password" minLength={8} required value={pw} onChange={(e) => setPw(e.target.value)} />
        <Button data-testid="reset-submit-btn" className="w-full bg-red-600 hover:bg-red-700">Update password</Button>
      </form>
    </Shell>
  );
}

export function VerifyEmail() {
  const [qs] = useSearchParams();
  const [state, setState] = useState("working");
  const [msg, setMsg] = useState("");
  const { refresh } = useAuth();
  const ran = useRef(false);
  useEffect(() => {
    if (ran.current) return; ran.current = true;
    api.post("/auth/verify-email", { token: qs.get("token") || "" })
      .then(() => { setState("ok"); refresh(); })
      .catch((e) => { setState("err"); setMsg(errMsg(e)); });
  }, [qs, refresh]);
  return (
    <Shell title="Email verification">
      {state === "working" && <p className="text-slate-400">Verifying…</p>}
      {state === "ok" && <p data-testid="verify-success-msg" className="text-emerald-300">Email verified. Your trial credits are now available.</p>}
      {state === "err" && <p data-testid="verify-error-msg" className="text-red-300">{msg}</p>}
      <Link to="/app" data-testid="verify-continue-link" className="mt-5 inline-block text-sm text-white underline underline-offset-4">Continue to studio</Link>
    </Shell>
  );
}
