import { Badge, SectionTitle } from '../ui';
import { toMinutes } from '../../utils/vfoot';
import type { MatchSide } from './MatchScoreHeader';

export interface PlayerLineVM {
  id: string | number;
  name: string;
  score: number;
}

export type SubEntryKind = 'covered' | 'uncovered' | 'disciplinary';

export interface SubEntryVM {
  starter: string;
  gapStart: number; // seconds
  gapEnd: number; // seconds
  kind: SubEntryKind;
  bench?: string;
  coveredSeconds?: number;
}

export interface SubReportVM {
  coveredSeconds: number;
  uncoveredSeconds: number;
  disciplinarySeconds: number;
  usedBenchCount: number;
  entries: SubEntryVM[];
}

export interface LineupVM {
  teamName: string;
  side: MatchSide;
  score: number;
  starters: PlayerLineVM[]; // host decides ordering
  bench: PlayerLineVM[];
  subReport?: SubReportVM;
}

export function LineupPanel({ lineup }: { lineup: LineupVM }) {
  const accent = lineup.side === 'home' ? 'text-green-600' : 'text-sky-600';
  const sub = lineup.subReport;
  return (
    <div>
      <div className="flex items-center justify-between">
        <SectionTitle>{lineup.teamName}</SectionTitle>
        <span className={`text-sm font-bold ${accent}`}>{lineup.score.toFixed(2)}</span>
      </div>

      <div className="mt-3 space-y-1">
        {lineup.starters.map((p) => (
          <div key={p.id} className="flex items-center justify-between text-sm">
            <span className="text-slate-700">{p.name}</span>
            <span className="font-mono text-xs text-slate-500">{p.score.toFixed(2)}</span>
          </div>
        ))}
      </div>

      {lineup.bench.length ? (
        <div className="mt-3 border-t border-slate-100 pt-2">
          <div className="text-[11px] uppercase tracking-wide text-slate-400">Panchina</div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate-500">
            {lineup.bench.map((p) => (
              <span key={p.id}>{p.name}</span>
            ))}
          </div>
        </div>
      ) : null}

      {sub ? <SubReport report={sub} /> : null}
    </div>
  );
}

function SubReport({ report }: { report: SubReportVM }) {
  return (
    <div className="mt-3 border-t border-slate-100 pt-2">
      <div className="text-[11px] uppercase tracking-wide text-slate-400">Sostituzioni temporali</div>
      <div className="mt-1 flex flex-wrap gap-2 text-[11px]">
        <Badge tone="green">coperti {toMinutes(report.coveredSeconds)}</Badge>
        {report.uncoveredSeconds ? <Badge tone="amber">scoperti {toMinutes(report.uncoveredSeconds)}</Badge> : null}
        {report.disciplinarySeconds ? (
          <Badge tone="red">espulsioni {toMinutes(report.disciplinarySeconds)}</Badge>
        ) : null}
        <Badge tone="slate">{report.usedBenchCount} subentri</Badge>
      </div>
      {report.entries.length ? (
        <div className="mt-2 space-y-1">
          {report.entries.map((s, i) => (
            <div key={`${s.starter}-${i}`} className="text-xs text-slate-600">
              <span className="text-slate-400">
                {toMinutes(s.gapStart)}–{toMinutes(s.gapEnd)}
              </span>{' '}
              {s.starter}{' '}
              {s.kind === 'covered' && s.bench ? (
                <>
                  <span className="text-slate-400">→</span> <b>{s.bench}</b>{' '}
                  <span className="text-green-600">({toMinutes(s.coveredSeconds)} coperti)</span>
                </>
              ) : s.kind === 'disciplinary' ? (
                <span className="text-red-600">— espulso, intervallo non copribile</span>
              ) : (
                <span className="text-amber-600">— scoperto, nessun subentro</span>
              )}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
