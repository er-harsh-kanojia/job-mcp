import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '../../components/Icon';
import { cx, Overlay } from '../../components/ui';
import { useLivePlatforms } from '../../lib/queries';
import { useApply } from '../../state/apply';
import { useSearch } from '../../state/search';
import { useTasks } from '../../state/tasks';
import { useUi } from '../../state/ui';

type Cmd = { label: string; hint: string; run: () => void };

export function CommandPalette() {
  const ui = useUi();
  const nav = useNavigate();
  const search = useSearch();
  const apply = useApply();
  const tasks = useTasks();
  const plats = useLivePlatforms();
  const [q, setQ] = useState('');
  const [idx, setIdx] = useState(0);
  const live = ui.mode === 'live';
  const close = () => ui.setPaletteOpen(false);

  const all = useMemo<Cmd[]>(
    () => [
      { label: 'Review resume', hint: 'Resume and prep', run: () => nav('/resume') },
      { label: `Prepare for ${ui.role} interviews`, hint: 'Resume and prep', run: () => nav('/resume?tab=prep') },
      {
        label: 'Re-analyse resume',
        hint: 'AI',
        run: () => {
          void tasks.startAnalysis(ui.role);
          nav('/resume');
        },
      },
      { label: 'Switch AI provider', hint: 'Claude or ChatGPT', run: () => nav('/profile#ai-provider') },
      {
        label: 'Run search',
        hint: 'All selected platforms',
        run: () => {
          void search.run();
          nav('/search');
        },
      },
      {
        label: `Bulk apply selected (${search.selected.length})`,
        hint: live ? 'Live' : 'Dry run',
        run: () => {
          apply.begin();
          nav('/apply');
        },
      },
      { label: 'Go to Dashboard', hint: 'Navigate', run: () => nav('/') },
      { label: 'Go to Search', hint: 'Navigate', run: () => nav('/search') },
      { label: 'Go to Applications', hint: 'Navigate', run: () => nav('/applications') },
      { label: 'Go to Platforms', hint: 'Navigate', run: () => nav('/platforms') },
      { label: 'Go to Profile', hint: 'Navigate', run: () => nav('/profile') },
      { label: live ? 'Switch to Dry run' : 'Switch to Live mode', hint: 'Mode', run: () => ui.setMode(live ? 'dry' : 'live') },
      { label: ui.theme === 'dark' ? 'Use light theme' : 'Use dark theme', hint: 'Theme', run: ui.toggleTheme },
      ...plats.map((p) => ({
        label: `Log in to ${p.name}`,
        hint: 'Opens a browser window',
        run: () => {
          void tasks.startLogin(String(p.id));
          nav('/platforms');
        },
      })),
      { label: 'Show failed applications', hint: 'Tracker', run: () => nav('/applications?status=failed') },
    ],
    [nav, ui, search, apply, tasks, plats, live],
  );

  const needle = q.trim().toLowerCase();
  const list = all.filter((c) => !needle || c.label.toLowerCase().includes(needle));
  const pi = Math.min(idx, Math.max(0, list.length - 1));
  const exec = (c: Cmd) => {
    close();
    c.run();
  };

  return (
    <Overlay variant="top" onClose={close} scrimLabel="Close command palette">
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <div className="pal-in">
          <Icon name="search" />
          <input
            autoFocus
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setIdx(0);
            }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setIdx(Math.min(list.length - 1, pi + 1));
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setIdx(Math.max(0, pi - 1));
              } else if (e.key === 'Enter' && list[pi]) {
                e.preventDefault();
                exec(list[pi]);
              }
            }}
            placeholder="Type a command…"
            aria-label="Command"
            role="combobox"
            aria-expanded="true"
            aria-controls="pal-list"
            aria-activedescendant={list[pi] ? `pal-${pi}` : undefined}
          />
          <span className="kbd">Esc</span>
        </div>
        <div className="pal-list" id="pal-list" role="listbox">
          {list.map((c, i) => (
            <button key={c.label} id={`pal-${i}`} role="option" aria-selected={i === pi} className={cx('pal-item', i === pi && 'pal-on')} onClick={() => exec(c)} onMouseMove={() => i !== pi && setIdx(i)}>
              <span>{c.label}</span>
              <span className="help">{c.hint}</span>
            </button>
          ))}
          {list.length === 0 && (
            <div className="help" style={{ padding: '12px 10px' }}>
              No matching commands.
            </div>
          )}
        </div>
        <div className="pal-foot">
          <span className="kbds">
            <span className="kbd">↑</span>
            <span className="kbd">↓</span> move
          </span>
          <span className="kbds">
            <span className="kbd">↵</span> run
          </span>
        </div>
      </div>
    </Overlay>
  );
}
