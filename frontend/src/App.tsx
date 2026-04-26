import { useState, useEffect } from "react";
import { NavSidebar } from "./components/nav-sidebar";
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

  // Dashboard has its own sidebar with Quick Actions, Export, etc.
  if (path === "/") return <Dashboard />;

  // All other pages use the shared NavSidebar
  let page;
  if (path === "/search") page = <SearchPage />;
  else if (path === "/people") page = <PeoplePage />;
  else if (path === "/dual-use") page = <DualUsePage />;
  else if (path === "/settings") page = <SettingsPage />;
  else page = <Dashboard />;

  return (
    <>
      <NavSidebar />
      <div className="pl-14">
        {page}
      </div>
    </>
  );
}

export default App;
