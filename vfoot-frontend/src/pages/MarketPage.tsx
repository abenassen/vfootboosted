import { Card, SectionTitle, Button, Badge } from '../components/ui';

export default function MarketPage() {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <SectionTitle>Mercato</SectionTitle>
        <div className="mt-2 flex items-center justify-between">
          <div>
            <div className="font-bold">Sessione aperta</div>
            <div className="text-sm text-slate-500">Offerte e scambi (mock)</div>
          </div>
          <Badge tone="green">aperto</Badge>
        </div>
      </Card>

      <Card className="p-4">
        <SectionTitle>Giocatori disponibili</SectionTitle>
        <div className="mt-3 space-y-3">
          {[
            { name: 'Giocatore J', price: 12, note: 'Buona copertura fascia' },
            { name: 'Giocatore K', price: 8, note: 'Affidabile minuti' },
            { name: 'Giocatore L', price: 15, note: 'Top value in area' }
          ].map((p) => (
            <div key={p.name} className="flex items-center justify-between gap-3 rounded-xl border border-slate-100 bg-slate-50 px-3 py-3">
              <div>
                <div className="font-semibold">{p.name} · €{p.price}</div>
                <div className="text-xs text-slate-500">{p.note}</div>
              </div>
              <Button variant="secondary" size="sm">Offri</Button>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
