// ============================================================
// OPSYN APP.TSX — Router tree, layout switch, auth boundary
// ============================================================

import { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useAuthStore } from './store/auth.store';
import AppShell from './layouts/AppShell';
import AuthLayout from './layouts/AuthLayout';

// ── Lazy-loaded pages (code splitting) ───────────────────────
const LoginPage          = lazy(() => import('./pages/auth/LoginPage'));
const ActivatePage       = lazy(() => import('./pages/auth/ActivatePage'));
const DashboardPage      = lazy(() => import('./pages/dashboard/DashboardPage'));
const TasksPage          = lazy(() => import('./pages/tasks/TasksPage'));
const DeptInboxPage      = lazy(() => import('./pages/tasks/DeptInboxPage'));
const DeletedTasksPage          = lazy(() => import('./pages/tasks/DeletedTasksPage'));
const AssignmentAnalyticsPage   = lazy(() => import('./pages/tasks/AssignmentAnalyticsPage'));
const ProjectsPage        = lazy(() => import('./pages/projects/ProjectsPage'));
const ProjectDetailPage   = lazy(() => import('./pages/projects/ProjectDetailPage'));
const ProjectPipelinePage = lazy(() => import('./pages/projects/ProjectPipelinePage'));
const OutagePage         = lazy(() => import('./pages/outage/OutagePage'));
const OutageDetailPage   = lazy(() => import('./pages/outage/OutageDetailPage'));
const StaffListPage      = lazy(() => import('./pages/staff/StaffListPage'));
const StaffDetailPage    = lazy(() => import('./pages/staff/StaffDetailPage'));
const StaffCreatePage    = lazy(() => import('./pages/staff/StaffCreatePage'));
const OnboardingPage     = lazy(() => import('./pages/onboarding/OnboardingPage'));
const RolesPage          = lazy(() => import('./pages/roles/RolesPage'));
const NotificationsPage  = lazy(() => import('./pages/notifications/NotificationsPage'));
const ReportsPage        = lazy(() => import('./pages/reports/ReportsPage'));
const AuditPage              = lazy(() => import('./pages/audit/AuditPage'));
const WorkflowBuilderPage    = lazy(() => import('./pages/org/WorkflowBuilderPage'));
const InfrastructurePage     = lazy(() => import('./pages/infrastructure/InfrastructurePage'));
const SettingsPage           = lazy(() => import('./pages/settings/SettingsPage'));
const ActivityPage           = lazy(() => import('./pages/activity/ActivityPage'));
const FormBuilderPage        = lazy(() => import('./pages/forms/FormBuilderPage'));
const ShiftSchedulerPage          = lazy(() => import('./pages/shifts/ShiftSchedulerPage'));
const InfrastructureSettingsPage  = lazy(() => import('./pages/infrastructure/InfrastructureSettingsPage'));
const InfrastructureUploadPage    = lazy(() => import('./pages/infrastructure/InfrastructureUploadPage'));
const InfrastructureDeletionPage  = lazy(() => import('./pages/infrastructure/InfrastructureDeletionPage'));
const InfrastructureAuditPage     = lazy(() => import('./pages/infrastructure/InfrastructureAuditPage'));
const FttxDesignerListPage        = lazy(() => import('./pages/fttx-designer/FttxDesignerListPage'));
const FttxDesignerWizardPage      = lazy(() => import('./pages/fttx-designer/FttxDesignerWizardPage'));
const NetworkMapPage              = lazy(() => import('./features/network-map/NetworkMapPage'));
const RegisterPage                = lazy(() => import('./pages/auth/RegisterPage'));
const FirstRunWizard              = lazy(() => import('./pages/onboarding/FirstRunWizard'));
const CustomersPage               = lazy(() => import('./pages/customers/CustomersPage'));
const CustomerDetailPage          = lazy(() => import('./pages/customers/CustomerDetailPage'));
const CustomerFormBuilderPage     = lazy(() => import('./pages/customers/CustomerFormBuilderPage'));
const FormBuilderNewPage          = lazy(() => import('./pages/form-builder/FormBuilderNewPage'));
const FormPreviewPage             = lazy(() => import('./pages/form-builder/FormPreviewPage'));
const FormSubmissionsPage         = lazy(() => import('./pages/form-builder/FormSubmissionsPage'));
const SchemaMigrationsPage        = lazy(() => import('./pages/form-builder/SchemaMigrationsPage'));

// ── Query client with sensible defaults ────────────────────
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime:          2 * 60 * 1000,   // 2 minutes
      retry:              1,
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: 0,
    },
  },
});

// ── Auth guard ─────────────────────────────────────────────
function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuth        = useAuthStore(s => s.isAuth);
  const hasHydrated   = useAuthStore(s => s._hasHydrated);
  if (!hasHydrated) return null;
  if (!isAuth) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

// ── Page loading fallback ──────────────────────────────────
function PageSpinner() {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      height: '100%', color: 'var(--chalk3)', fontSize: '13px',
      fontFamily: 'var(--font)',
    }}>
      <span style={{ opacity: 0.6 }}>Loading…</span>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={<PageSpinner />}>
          <Routes>
            {/* ── Public ── */}
            <Route element={<AuthLayout />}>
              <Route path="/login"    element={<LoginPage />} />
              <Route path="/activate" element={<ActivatePage />} />
              <Route path="/register" element={<RegisterPage />} />
            </Route>

            {/* ── Post-registration setup (auth required, no AppShell chrome) ── */}
            <Route path="/setup" element={<RequireAuth><FirstRunWizard /></RequireAuth>} />

            {/* ── Protected ── */}
            <Route element={<RequireAuth><AppShell /></RequireAuth>}>
              <Route index                    element={<Navigate to="/dashboard" replace />} />
              <Route path="dashboard"         element={<DashboardPage />} />
              <Route path="tasks"             element={<TasksPage />} />
              <Route path="tasks/inbox"       element={<DeptInboxPage />} />
              <Route path="tasks/deleted"     element={<DeletedTasksPage />} />
              <Route path="tasks/analytics"   element={<AssignmentAnalyticsPage />} />
              <Route path="projects"              element={<ProjectsPage />} />
              <Route path="projects/:id"          element={<ProjectDetailPage />} />
              <Route path="projects/:id/pipeline" element={<ProjectPipelinePage />} />
              <Route path="outage"            element={<OutagePage />} />
              <Route path="outage/:id"       element={<OutageDetailPage />} />
              <Route path="staff"             element={<StaffListPage />} />
              <Route path="staff/new"         element={<StaffCreatePage />} />
              <Route path="staff/:id"         element={<StaffDetailPage />} />
              <Route path="onboarding"        element={<OnboardingPage />} />
              <Route path="roles"             element={<RolesPage />} />
              <Route path="notifications"     element={<NotificationsPage />} />
              <Route path="reports"           element={<ReportsPage />} />
              <Route path="audit"             element={<AuditPage />} />
              <Route path="org/workflows"    element={<WorkflowBuilderPage />} />
              <Route path="infrastructure"          element={<InfrastructurePage />} />
              <Route path="infrastructure/upload"    element={<InfrastructureUploadPage />} />
              <Route path="infrastructure/deletion"  element={<InfrastructureDeletionPage />} />
              <Route path="infrastructure/settings"  element={<InfrastructureSettingsPage />} />
              <Route path="infrastructure/audit"     element={<InfrastructureAuditPage />} />
              <Route path="fttx-designer"            element={<FttxDesignerListPage />} />
              <Route path="fttx-designer/:runId"     element={<FttxDesignerWizardPage />} />
              <Route path="network"                  element={<NetworkMapPage />} />
              <Route path="settings"                  element={<SettingsPage />} />
              <Route path="settings/forms/:context"  element={<FormBuilderPage />} />
              <Route path="activity"                 element={<ActivityPage />} />
              <Route path="shifts"                   element={<ShiftSchedulerPage />} />
              <Route path="customers"               element={<CustomersPage />} />
              <Route path="customers/forms"         element={<CustomerFormBuilderPage />} />
              <Route path="customers/:id"           element={<CustomerDetailPage />} />
              <Route path="form-builder"                              element={<FormBuilderNewPage />} />
              <Route path="form-builder/:schemaId"              element={<FormBuilderNewPage />} />
              <Route path="form-builder/:schemaId/preview"      element={<FormPreviewPage />} />
<Route path="form-builder/:schemaId/submissions"       element={<FormSubmissionsPage />} />
              <Route path="form-builder/:schemaId/migrations"        element={<SchemaMigrationsPage />} />
            </Route>

            {/* ── 404 fallback ── */}
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
