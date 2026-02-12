import { Card, SectionTitle, Badge } from '../components/ui';

export default function LeaguePage() {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <SectionTitle>Classifica</SectionTitle>
        <div className="mt-3 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="py-2">#</th>
                <th>Squadra</th>
                <th className="text-right">Pt</th>
              </tr>
            </thead>
            <tbody>
              {[
                { name: 'Casa FC', pt: 46 },
                { name: 'Trasferta FC', pt: 44 },
                { name: 'Atletico Mock', pt: 39 },
                { name: 'Real Lorem', pt: 34 }
              ].map((r, i) => (
                <tr key={r.name} className="border-t">
                  <td className="py-2 font-semibold">{i + 1}</td>
                  <td className="py-2 font-semibold">{r.name} {r.name === 'Casa FC' ? <Badge tone="green">tu</Badge> : null}</td>
                  <td className="py-2 text-right font-bold">{r.pt}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-4">
          <SectionTitle>Calendario</SectionTitle>
          <div className="mt-2 text-sm text-slate-600">
            Giornata 24: Casa FC vs Trasferta FC
          </div>
          <div className="mt-1 text-sm text-slate-600">
            Giornata 25: Casa FC vs Atletico Mock
          </div>
        </Card>

        <Card className="p-4">
          <SectionTitle>Regole (estratto)</SectionTitle>
          <ul className="mt-2 space-y-2 text-sm text-slate-700">
            <li>• Formazione: selezione di 11 giocatori (ruoli non vincolanti).</li>
            <li>• Punteggio: somma base + contributo zone (campo a griglia).</li>
            <li>• Bilanciamento: emerge da copertura/qualità nelle zone.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
