import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import DashboardPage from './pages/DashboardPage'
import DocumentsPage from './pages/DocumentsPage'
import ProjectsPage from './pages/ProjectsPage'
import ProjectWorkspace from './pages/ProjectWorkspace'
import CollectionsPage from './pages/CollectionsPage'
import SearchPage from './pages/SearchPage'
import DocumentDetailPage from './pages/DocumentDetailPage'
import UsersPage from './pages/UsersPage'
import GroupsPage from './pages/GroupsPage'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/SettingsPage'
import AuditLogPage from './pages/AuditLogPage'
import UsageDashboardPage from './pages/UsageDashboardPage'
import DictionaryPage from './pages/DictionaryPage'
import WorkflowsPage from './pages/WorkflowsPage'
import WorkflowEditorPage from './pages/WorkflowEditorPage'
import WorkflowRunsPage from './pages/WorkflowRunsPage'
import ProcessingStatusPage from './pages/ProcessingStatusPage'
import CleaningRulesPage from './pages/CleaningRulesPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="documents/:id" element={<DocumentDetailPage />} />
        <Route path="processing-status" element={<ProcessingStatusPage />} />
        <Route path="projects" element={<ProjectsPage />}>
          <Route path=":projectId" element={<ProjectWorkspace />}>
            <Route index element={<Navigate to="collections" replace />} />
            <Route path="collections" element={<CollectionsPage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="documents/:id" element={<DocumentDetailPage />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="chat/:conversationId" element={<ChatPage />} />
            <Route path="workflows" element={<WorkflowsPage />} />
            <Route path="workflows/:id/edit" element={<WorkflowEditorPage />} />
            <Route path="workflows/:id/runs" element={<WorkflowRunsPage />} />
          </Route>
        </Route>
        <Route path="collections" element={<CollectionsPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="chat/:conversationId" element={<ChatPage />} />
        <Route path="workflows" element={<WorkflowsPage />} />
        <Route path="workflows/:id/edit" element={<WorkflowEditorPage />} />
        <Route path="workflows/:id/runs" element={<WorkflowRunsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="groups" element={<GroupsPage />} />
        <Route path="audit-logs" element={<AuditLogPage />} />
        <Route path="usage" element={<UsageDashboardPage />} />
        <Route path="dictionary" element={<DictionaryPage />} />
        <Route path="cleaning-rules" element={<CleaningRulesPage />} />
      </Route>
    </Routes>
  )
}
