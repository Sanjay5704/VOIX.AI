import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "../lib/api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState(getToken() ? "checking" : "anonymous");

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setStatus("anonymous");
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout); // an expired JWT anywhere logs the user out
  }, [logout]);

  useEffect(() => {
    if (status !== "checking") return;
    api
      .me()
      .then((u) => {
        setUser(u);
        setStatus("authenticated");
      })
      .catch(logout);
  }, [status, logout]);

  const accept = useCallback((tokenResponse) => {
    setToken(tokenResponse.access_token);
    setUser(tokenResponse.user);
    setStatus("authenticated");
  }, []);

  const value = useMemo(
    () => ({
      user,
      status,
      login: async (email, password) => accept(await api.login(email, password)),
      register: async (email, password) => accept(await api.register(email, password)),
      logout,
    }),
    [user, status, accept, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
