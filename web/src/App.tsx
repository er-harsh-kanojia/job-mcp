import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Shell } from './features/shell/Shell';
import { DashboardPage } from './features/dashboard/DashboardPage';
import { SearchPage } from './features/search/SearchPage';
import { ApplyPage } from './features/apply/ApplyPage';
import { ApplicationsPage } from './features/applications/ApplicationsPage';
import { ResumePage } from './features/resume/ResumePage';
import { PlatformsPage } from './features/platforms/PlatformsPage';
import { ProfilePage } from './features/profile/ProfilePage';
import { shouldRetry } from './lib/queries';
import { UiProvider } from './state/ui';
import { SearchProvider } from './state/search';
import { ApplyProvider } from './state/apply';
import { TasksProvider } from './state/tasks';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: shouldRetry, refetchOnWindowFocus: false, staleTime: 10_000 },
    mutations: { retry: false },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <UiProvider>
        <SearchProvider>
          <ApplyProvider>
            <TasksProvider>
              <BrowserRouter>
                <Routes>
                  <Route element={<Shell />}>
                    <Route index element={<DashboardPage />} />
                    <Route path="search" element={<SearchPage />} />
                    <Route path="apply" element={<ApplyPage />} />
                    <Route path="applications" element={<ApplicationsPage />} />
                    <Route path="resume" element={<ResumePage />} />
                    <Route path="platforms" element={<PlatformsPage />} />
                    <Route path="profile" element={<ProfilePage />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Route>
                </Routes>
              </BrowserRouter>
            </TasksProvider>
          </ApplyProvider>
        </SearchProvider>
      </UiProvider>
    </QueryClientProvider>
  );
}
