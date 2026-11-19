import { lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, RequireAdmin, RequireAuth } from "./auth";
import { ThemeProvider } from "./theme";
import { ToastProvider } from "./components/Toast";
import { ConfirmProvider } from "./components/ConfirmDialog";
import Layout from "./components/Layout";
import Create from "./pages/Create";
import Login from "./pages/Login";

const Admin = lazy(() => import("./pages/Admin"));
const Agent = lazy(() => import("./pages/Agent"));
const Batch = lazy(() => import("./pages/Batch"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Jobs = lazy(() => import("./pages/Jobs"));
const KnowledgeBase = lazy(() => import("./pages/KnowledgeBase"));
const Models = lazy(() => import("./pages/Models"));
const PasteImage = lazy(() => import("./pages/PasteImage"));
const Pipeline = lazy(() => import("./pages/Pipeline"));
const QuickTools = lazy(() => import("./pages/QuickTools"));
const Recipes = lazy(() => import("./pages/Recipes"));
const TranscriptEditor = lazy(() => import("./pages/TranscriptEditor"));
const ToolPage = lazy(() => import("./pages/ToolPage"));
const WorkflowRun = lazy(() => import("./pages/WorkflowRun"));

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <ConfirmProvider>
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
              <Route path="/" element={<Create />} />
              <Route path="/tools" element={<Dashboard />} />
              <Route path="/recipes" element={<Recipes />} />
              <Route path="/runs/:id" element={<WorkflowRun />} />
              <Route path="/runs/:id/transcript/:fileId" element={<TranscriptEditor />} />
              <Route path="/assistant" element={<Agent />} />
              <Route path="/knowledge" element={<KnowledgeBase />} />
              <Route path="/paste" element={<PasteImage />} />
              <Route path="/tool/:slug" element={<ToolPage />} />
              <Route path="/batch" element={<Batch />} />
              <Route path="/pipeline" element={<Pipeline />} />
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
        </ConfirmProvider>
      </ToastProvider>
    </ThemeProvider>
  );
}
