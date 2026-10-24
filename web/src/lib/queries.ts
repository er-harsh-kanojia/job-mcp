import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, isApiError, isUnreachable } from '../api';
import type { AiProvider, AiProviderInfo, AiSettings, ApplicationsQuery, PlatformInfo, Review } from '../api/types';

export const qk = {
  health: ['health'] as const,
  platforms: ['platforms'] as const,
  aiSettings: ['ai-settings'] as const,
  lastSearch: ['search', 'last'] as const,
  stats: ['stats'] as const,
  applications: (q: ApplicationsQuery) => ['applications', q] as const,
  profile: ['profile'] as const,
  review: (role: string) => ['review', role] as const,
};

/** Don't retry client errors (4xx) or AI-not-configured; retry network blips once. */
export function shouldRetry(count: number, err: unknown): boolean {
  if (isApiError(err) && err.status >= 400 && err.status < 500) return false;
  if (isApiError(err) && err.code === 'ai_not_configured') return false;
  return count < 1;
}

export function useHealth() {
  return useQuery({
    queryKey: qk.health,
    queryFn: () => api.health(),
    // Poll every 10 s while the server is unreachable, every 30 s otherwise.
    refetchInterval: (q) => (q.state.error ? 10_000 : 30_000),
    retry: false,
    refetchOnWindowFocus: true,
  });
}

/** True once health has failed with a connection error (and keeps failing). */
export function useBackendDown(): boolean {
  const h = useHealth();
  return !!h.error && isUnreachable(h.error);
}

export function usePlatforms() {
  return useQuery({ queryKey: qk.platforms, queryFn: () => api.platforms().then((r) => r.platforms), refetchInterval: 60_000 });
}

export function useLivePlatforms(): PlatformInfo[] {
  const { data } = usePlatforms();
  return (data ?? []).filter((p) => p.live);
}

export function useAiSettings() {
  return useQuery({ queryKey: qk.aiSettings, queryFn: () => api.aiSettings() });
}

const PROVIDER_FALLBACK: Record<AiProvider, Pick<AiProviderInfo, 'name' | 'short'>> = {
  anthropic: { name: 'Claude (Anthropic)', short: 'Claude' },
  openai: { name: 'ChatGPT (OpenAI)', short: 'ChatGPT' },
  local: { name: 'Local model (LM Studio / Ollama)', short: 'Local AI' },
};
export const PROVIDER_KEY: Record<AiProvider, string> = { anthropic: 'ANTHROPIC_API_KEY', openai: 'OPENAI_API_KEY', local: 'JOB_MCP_LOCAL_BASE_URL' };
/** What to do to enable a provider: an API key in .env, or (local) a running model server. */
export function providerSetupHint(id: AiProvider): string {
  return id === 'local'
    ? "start LM Studio's server (Developer, Start server) with a model loaded"
    : `add ${PROVIDER_KEY[id]} to D:\\Job-MCP\\.env and restart`;
}

/** The selected AI provider, for copy like "Practise with Claude" / "Practise with ChatGPT". */
export function useAiProvider(): { id: AiProvider; short: string; name: string; configured: boolean; model: string | null; envKey: string } {
  const s = useAiSettings().data;
  const h = useHealth().data;
  const id: AiProvider = s?.provider ?? h?.ai.provider ?? 'anthropic';
  const info = s?.providers.find((p) => p.id === id);
  return {
    id,
    short: info?.short ?? PROVIDER_FALLBACK[id].short,
    name: info?.name ?? h?.ai.provider_name ?? PROVIDER_FALLBACK[id].name,
    configured: info?.configured ?? h?.ai.configured ?? true,
    model: info?.model ?? h?.ai.model ?? null,
    envKey: PROVIDER_KEY[id],
  };
}

export function useSetAiProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: AiProvider) => api.setAiProvider(p),
    onSuccess: (data: AiSettings) => {
      qc.setQueryData(qk.aiSettings, data);
      void qc.invalidateQueries({ queryKey: qk.health });
      void qc.invalidateQueries({ queryKey: ['review'] });
    },
  });
}

export function useLastSearch() {
  return useQuery({ queryKey: qk.lastSearch, queryFn: () => api.lastSearch(), staleTime: Infinity });
}

export function useStats() {
  return useQuery({ queryKey: qk.stats, queryFn: () => api.stats() });
}

export function useApplications(q: ApplicationsQuery) {
  return useQuery({ queryKey: qk.applications(q), queryFn: () => api.applications(q).then((r) => r.applications), placeholderData: (prev) => prev });
}

export function useProfile() {
  return useQuery({ queryKey: qk.profile, queryFn: () => api.profile(), staleTime: 60_000 });
}

export function useReview(role: string) {
  return useQuery<Review | null>({ queryKey: qk.review(role), queryFn: () => api.review(role), retry: shouldRetry, staleTime: 30_000 });
}
