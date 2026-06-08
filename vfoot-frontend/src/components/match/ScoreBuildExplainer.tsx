export interface ScoreBuildVM {
  base: number;
  scoreScale: number;
  boost: number;
  meanMargin: number;
  boostedMargin: number;
  zoneCount: number;
  homeName: string;
  awayName: string;
  homeScore: number;
  awayScore: number;
  homeGkAdjustment: number; // points added to home score by the away keeper (usually ≤ 0)
  awayGkAdjustment: number;
}

// Explains, with the actual numbers, how the per-zone duels aggregate into the
// final team scores — so the user understands that ALL zones contribute, not
// only the few highlighted ones.
export function ScoreBuildExplainer({ vm }: { vm: ScoreBuildVM }) {
  const favoursHome = vm.meanMargin >= 0;
  return (
    <div className="space-y-3 text-sm">
      <p className="text-slate-600">
        Ogni zona è un <b>duello</b>: si confronta il tuo terzo offensivo col terzo difensivo avversario (e
        viceversa). Il punteggio parte da una base e si sposta in base alla <b>media dei duelli sulle{' '}
        {vm.zoneCount} zone con presenza</b>. Il contributo di ogni zona è <b>saturato</b>: <i>vincere</i> una zona
        conta, <i>stravincerla</i> rende sempre meno — quindi conviene contendere più zone e mettere i difensori
        dove l'avversario attacca, non ammassare tutti i big nello stesso punto.
      </p>

      <div className="flex flex-wrap items-center gap-2 rounded-xl bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700">
        <span>punteggio</span>
        <span className="text-slate-400">=</span>
        <Chip label="base" value={vm.base.toFixed(1)} />
        <span className="text-slate-400">±</span>
        <Chip label="scala" value={vm.scoreScale.toFixed(1)} />
        <span className="text-slate-400">×</span>
        <Chip label={`boost ${vm.boost}× margine medio`} value={vm.meanMargin.toFixed(3)} />
      </div>

      <div className="flex items-center justify-center gap-4">
        <TeamScore name={vm.homeName} score={vm.homeScore} accent="text-green-600" up={favoursHome} />
        <span className="text-xs text-slate-400">
          margine medio{' '}
          <b className={favoursHome ? 'text-green-600' : 'text-sky-600'}>
            {vm.meanMargin >= 0 ? '+' : ''}
            {vm.meanMargin.toFixed(3)}
          </b>
        </span>
        <TeamScore name={vm.awayName} score={vm.awayScore} accent="text-sky-600" up={!favoursHome} />
      </div>

      {vm.homeGkAdjustment || vm.awayGkAdjustment ? (
        <p className="text-[11px] text-slate-500">
          Il <b>portiere</b> è valutato a parte (gol evitati) e <b>riduce le chance dell'avversario</b>:
          {vm.homeGkAdjustment ? (
            <> il portiere di {vm.awayName} ha inciso <b>{vm.homeGkAdjustment.toFixed(1)}</b> sul punteggio di {vm.homeName};</>
          ) : null}
          {vm.awayGkAdjustment ? (
            <> il portiere di {vm.homeName} ha inciso <b>{vm.awayGkAdjustment.toFixed(1)}</b> su {vm.awayName}.</>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-baseline gap-1 rounded bg-white px-1.5 py-0.5 shadow-sm">
      <span className="text-[10px] text-slate-400">{label}</span>
      <b className="text-slate-800">{value}</b>
    </span>
  );
}

function TeamScore({ name, score, accent, up }: { name: string; score: number; accent: string; up: boolean }) {
  return (
    <div className="text-center">
      <div className="max-w-[8rem] truncate text-[11px] text-slate-500">{name}</div>
      <div className={`text-lg font-black ${up ? accent : 'text-slate-700'}`}>{score.toFixed(2)}</div>
    </div>
  );
}
