import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";

const Ctx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null = checking, false = signed out

  const refresh = useCallback(async () => {
    if (!localStorage.getItem("anchorai_token")) return setUser(false);
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch {
      setUser(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const signIn = (data) => {
    localStorage.setItem("anchorai_token", data.token);
    setUser(data.user);
  };
  const signOut = async () => {
    try { await api.post("/auth/logout"); } catch { /* session may already be gone */ }
    localStorage.removeItem("anchorai_token");
    setUser(false);
  };

  return <Ctx.Provider value={{ user, signIn, signOut, refresh }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
