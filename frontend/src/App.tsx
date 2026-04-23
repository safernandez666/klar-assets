import { useState, useEffect } from "react";
import Dashboard from "./pages/dashboard";
import SearchPage from "./pages/search";

function App() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  if (path === "/search") return <SearchPage />;
  return <Dashboard />;
}

export default App;
