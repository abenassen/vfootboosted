import { useEffect } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { useCompetitionContext } from '../league/CompetitionContext';

// Deep-link `/competitions/:id` no longer has its own calendar (that caused two
// parallel "Partite" views). It just selects the competition in the switcher and
// funnels into the unified, switcher-driven calendar.
export default function CompetitionPage() {
  const { competitionId } = useParams();
  const { setSelectedCompetitionId } = useCompetitionContext();
  useEffect(() => {
    if (competitionId) setSelectedCompetitionId(Number(competitionId));
  }, [competitionId, setSelectedCompetitionId]);
  return <Navigate to="/matches" replace />;
}
