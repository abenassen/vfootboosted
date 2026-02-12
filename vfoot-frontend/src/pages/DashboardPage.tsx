import { Link } from 'react-router-dom';
import { Badge, Button, Card, SectionTitle } from '../components/ui';

export default function DashboardPage() {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <SectionTitle>Prossima giornata</SectionTitle>
        <div className="mt-2 flex items-end justify-between gap-4">
          <div>
            <div className="text-2xl font-black">Giornata 24</div>
            <div className="text-sm text-slate-500">Deadline: 13/02 20:45</div>
          </div>
          <Badge tone="amber">⚠ Formazione da controllare</Badge>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link to="/squad/formation"><Button>Vai alla formazione</Button></Link>
          <Link to="/matches"><Button variant="secondary">Vedi partite</Button></Link>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-4">
          <SectionTitle>Prossimo match</SectionTitle>
          <div className="mt-2 flex items-center justify-between">
            <div>
              <div className="font-bold">Casa FC vs Trasferta FC</div>
              <div className="text-sm text-slate-500">Preview: 72.4 – 68.1</div>
            </div>
            <Link to="/matches/M778"><Button variant="secondary" size="sm">Dettagli</Button></Link>
          </div>
        </Card>

        <Card className="p-4">
          <SectionTitle>Avvisi</SectionTitle>
          <ul className="mt-2 space-y-2 text-sm">
            <li className="flex items-start gap-2"><span>•</span><span>Mercato aperto (fino a domani)</span></li>
            <li className="flex items-start gap-2"><span>•</span><span>1 titolare a rischio minutaggio</span></li>
            <li className="flex items-start gap-2"><span>•</span><span>Copertura fascia destra bassa (stima)</span></li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
