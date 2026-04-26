import { useState, useEffect } from "react";
import Dashboard from "./pages/dashboard";
import SearchPage from "./pages/search";
import PeoplePage from "./pages/people";
import DualUsePage from "./pages/dual-use";
import SettingsPage from "./pages/settings";

function App() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  if (path === "/search") return <SearchPage />;
  if (path === "/people") return <PeoplePage />;
  if (path === "/dual-use") return <DualUsePage />;
  if (path === "/settings") return <SettingsPage />;
  return <Dashboard />;
}

export default App;
