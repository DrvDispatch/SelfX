import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, RequireAdmin, RequireAuth } from "./auth";
import { ThemeProvider } from "./theme";
import Layout from "./components/Layout";
import Admin from "./pages/Admin";
import Agent from "./pages/Agent";
import Dashboard from "./pages/Dashboard";
import Jobs from "./pages/Jobs";
import KnowledgeBase from "./pages/KnowledgeBase";
import Login from "./pages/Login";
import Models from "./pages/Models";
import QuickTools from "./pages/QuickTools";
import ToolPage from "./pages/ToolPage";

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route path="/" element={<Dashboard />} />
              <Route path="/assistant" element={<Agent />} />
              <Route path="/knowledge" element={<KnowledgeBase />} />
              <Route path="/tool/:slug" element={<ToolPage />} />
              <Route path="/jobs" element={<Jobs />} />
              <Route path="/quick-tools" element={<QuickTools />} />
              <Route
                path="/admin"
                element={
                  <RequireAdmin>
                    <Admin />
                  </RequireAdmin>
                }
              />
              <Route
                path="/models"
                element={
                  <RequireAdmin>
                    <Models />
                  </RequireAdmin>
                }
              />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
