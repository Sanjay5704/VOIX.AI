import React, { createContext, useContext } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { useHealth } from "../hooks/useData.js";
import OnAirBadge from "./OnAirBadge.jsx";

const HealthContext = createContext(null);
export const useWorkerHealth = () => useContext(HealthContext);

const NAV = [
  { to: "/studio", label: "Studio", hint: "Write & render" },
  { to: "/history", label: "History", hint: "Past renders" },
  { to: "/voices", label: "Voices", hint: "Library & cloning" },
  { to: "/keys", label: "API keys", hint: "Developer access" },
  { to: "/usage", label: "Usage", hint: "Quota & metering" },
  { to: "/benchmarks", label: "Benchmarks", hint: "Engines, measured" },
  { to: "/analytics", label: "Analytics", hint: "Platform health", admin: true },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const health = useHealth();

  return (
    <HealthContext.Provider value={health}>
      <div className="shell">
        <aside className="rail">
          <div className="brand">
            <span className="brand__mark" aria-hidden="true">
              <i />
              <i />
              <i />
              <i />
            </span>
            <span className="brand__name">VOIX</span>
          </div>

          <nav className="rail__nav" aria-label="Main">
            {NAV.filter((item) => !item.admin || user?.is_admin).map((item, i) => (
              <NavLink key={item.to} to={item.to} className="rail__link">
                <span className="rail__index">{String(i + 1).padStart(2, "0")}</span>
                <span className="rail__text">
                  <span className="rail__label">{item.label}</span>
                  <span className="rail__hint">{item.hint}</span>
                </span>
              </NavLink>
            ))}
          </nav>

          <div className="rail__foot">
            <a className="rail__docs" href={`${import.meta.env.VITE_API_BASE_URL || ""}/docs`} target="_blank" rel="noreferrer">
              API reference ↗
            </a>
          </div>
        </aside>

        <div className="stage">
          <header className="topbar">
            <OnAirBadge health={health} />
            <div className="topbar__user">
              <span className="topbar__plan">{user?.plan ?? "free"}</span>
              <span className="topbar__email" title={user?.email}>
                {user?.email}
              </span>
              <button type="button" className="btn btn--ghost btn--sm" onClick={logout}>
                Sign out
              </button>
            </div>
          </header>
          <main className="content">
            <Outlet />
          </main>
        </div>
      </div>
    </HealthContext.Provider>
  );
}
