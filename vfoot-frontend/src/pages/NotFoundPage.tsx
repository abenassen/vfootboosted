import { Link } from 'react-router-dom';
import { Button, Card } from '../components/ui';

export default function NotFoundPage() {
  return (
    <div className="mx-auto max-w-lg">
      <Card className="p-6 text-center">
        <div className="text-2xl font-black">404</div>
        <div className="mt-2 text-sm text-slate-500">Pagina non trovata.</div>
        <div className="mt-4">
          <Link to="/home"><Button>Torna alla dashboard</Button></Link>
        </div>
      </Card>
    </div>
  );
}
