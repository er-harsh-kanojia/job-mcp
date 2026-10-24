import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type Theme = 'light' | 'dark';
export type Mode = 'dry' | 'live';
export const ROLES = ['GenAI Engineer', 'LLM Engineer', 'ML Engineer'] as const;

export function readLS(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
export function writeLS(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // storage unavailable (private mode); the setting just won't persist
  }
}

function initialTheme(): Theme {
  const t = readLS('jobmcp.theme');
  if (t === 'light' || t === 'dark') return t;
  const attr = document.documentElement.getAttribute('data-theme');
  return attr === 'dark' ? 'dark' : 'light';
}

export type InterviewTarget = { questionId: string; question: string; role: string; round?: string };

type UiCtx = {
  theme: Theme;
  toggleTheme: () => void;
  /** Dry run vs Live. Not persisted: every session starts in Dry run, on purpose. */
  mode: Mode;
  setMode: (m: Mode) => void;
  role: string;
  setRole: (r: string) => void;
  paletteOpen: boolean;
  setPaletteOpen: (o: boolean) => void;
  navOpen: boolean;
  setNavOpen: (o: boolean) => void;
  interview: InterviewTarget | null;
  openInterview: (t: InterviewTarget) => void;
  closeInterview: () => void;
};

const Ctx = createContext<UiCtx | null>(null);

export function UiProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [mode, setMode] = useState<Mode>('dry');
  const [role, setRoleState] = useState<string>(() => readLS('jobmcp.role') || ROLES[0]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [interview, setInterview] = useState<InterviewTarget | null>(null);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    writeLS('jobmcp.theme', theme);
  }, [theme]);

  const toggleTheme = useCallback(() => setTheme((t) => (t === 'dark' ? 'light' : 'dark')), []);
  const setRole = useCallback((r: string) => {
    setRoleState(r);
    writeLS('jobmcp.role', r);
  }, []);

  const value = useMemo<UiCtx>(
    () => ({
      theme,
      toggleTheme,
      mode,
      setMode,
      role,
      setRole,
      paletteOpen,
      setPaletteOpen,
      navOpen,
      setNavOpen,
      interview,
      openInterview: setInterview,
      closeInterview: () => setInterview(null),
    }),
    [theme, toggleTheme, mode, role, setRole, paletteOpen, navOpen, interview],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useUi(): UiCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error('useUi outside UiProvider');
  return c;
}
