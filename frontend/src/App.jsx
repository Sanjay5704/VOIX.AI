import React from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext.jsx";
import Layout from "./components/Layout.jsx";
import ApiKeys from "./pages/ApiKeys.jsx";
import AuthPage from "./pages/AuthPage.jsx";
import { History, JobDetail } from "./pages/History.jsx";
import Studio from "./pages/Studio.jsx";
import Usage from "./pages/Usage.jsx";
import Voices from "./pages/Voices.jsx";

function RequireAuth({ children }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "checking") return <div className="boot">VOIX</div>;
  if (status !== "authenticated") return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return children;
}

function GuestOnly({ children }) {
  const { status } = useAuth();
  if (status === "checking") return <div className="boot">VOIX</div>;
  return status === "authenticated" ? <Navigate to="/studio" replace /> : children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<GuestOnly><AuthPage mode="login" /></GuestOnly>} />
      <Route path="/register" element={<GuestOnly><AuthPage mode="register" /></GuestOnly>} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route path="/studio" element={<Studio />} />
        <Route path="/history" element={<History />} />
        <Route path="/jobs/:id" element={<JobDetail />} />
        <Route path="/voices" element={<Voices />} />
        <Route path="/keys" element={<ApiKeys />} />
        <Route path="/usage" element={<Usage />} />
      </Route>
      <Route path="*" element={<Navigate to="/studio" replace />} />
    </Routes>
  );
}
