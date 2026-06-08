from __future__ import annotations

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

from realdata.models import CARD_RED, CARD_SECOND_YELLOW, Match, MatchDisciplinaryEvent, PlayerOnPitchInterval


class Command(BaseCommand):
    help = "Check on-pitch timeline consistency for realdata intervals and disciplinary events."

    def add_arguments(self, parser):
        parser.add_argument("--max-examples", type=int, default=10)

    def handle(self, *args, **options):
        max_examples = int(options["max_examples"])
        intervals_by_team: dict[tuple[int, str], list[tuple[int, int, int]]] = defaultdict(list)
        for row in PlayerOnPitchInterval.objects.values(
            "match_id",
            "team_side",
            "player_id",
            "start_elapsed_seconds",
            "end_elapsed_seconds",
        ):
            start = int(row["start_elapsed_seconds"])
            end = int(row["end_elapsed_seconds"])
            if end <= start:
                continue
            intervals_by_team[(int(row["match_id"]), str(row["team_side"]))].append((start, end, int(row["player_id"])))

        sent_off_by_team: dict[tuple[int, str], list[tuple[int, int]]] = defaultdict(list)
        for row in MatchDisciplinaryEvent.objects.filter(card_type__in=[CARD_RED, CARD_SECOND_YELLOW]).values(
            "match_id",
            "team_side",
            "player_id",
            "elapsed_seconds",
        ):
            if row["player_id"] is None:
                continue
            sent_off_by_team[(int(row["match_id"]), str(row["team_side"]))].append(
                (int(row["elapsed_seconds"]), int(row["player_id"]))
            )

        match_labels = {
            match.id: f"{match.external_id} {match.home_team} vs {match.away_team}"
            for match in Match.objects.select_related("home_team", "away_team")
        }

        raw_over_11 = []
        adjusted_over_11 = []
        red_no_raw_drop = []
        max_raw = 0
        max_adjusted = 0
        invalid_intervals = []
        player_overlaps = []
        exact_duplicates = Counter()
        active_at_zero = Counter()
        low_active_segments = []

        intervals_by_player: dict[tuple[int, int], list[tuple[int, int, int, str, str]]] = defaultdict(list)
        for key, rows in intervals_by_team.items():
            for start, end, player_id in rows:
                if end <= start:
                    invalid_intervals.append((key, start, end, player_id))
                intervals_by_player[(key[0], player_id)].append((start, end, player_id, key[1], ""))
                exact_duplicates[(key[0], key[1], player_id, start, end)] += 1

        for key, rows in intervals_by_player.items():
            rows = sorted(rows)
            for first, second in zip(rows, rows[1:]):
                if second[0] < first[1]:
                    player_overlaps.append((key, first, second))

        for key, rows in intervals_by_team.items():
            times = {time for start, end, _ in rows for time in (start, end)}
            times.update(time for time, _ in sent_off_by_team.get(key, []))
            active_at_zero[len({player_id for start, end, player_id in rows if start <= 0 < end})] += 1
            for time in sorted(times):
                raw_active = {player_id for start, end, player_id in rows if start <= time < end}
                sent_off = {player_id for red_time, player_id in sent_off_by_team.get(key, []) if red_time <= time}
                adjusted_active = raw_active - sent_off
                max_raw = max(max_raw, len(raw_active))
                max_adjusted = max(max_adjusted, len(adjusted_active))
                if len(raw_active) > 11:
                    raw_over_11.append((key, time, len(raw_active)))
                if len(adjusted_active) > 11:
                    adjusted_over_11.append((key, time, len(adjusted_active)))

            sorted_times = sorted(times)
            for start, end in zip(sorted_times, sorted_times[1:]):
                if end <= start:
                    continue
                raw_active = {player_id for left, right, player_id in rows if left <= start and end <= right}
                if len(raw_active) < 10 and end - start >= 60:
                    red_count = sum(1 for red_time, _ in sent_off_by_team.get(key, []) if red_time <= start)
                    low_active_segments.append((key, start, end, len(raw_active), red_count))

        for key, red_rows in sent_off_by_team.items():
            rows = intervals_by_team.get(key, [])
            for red_time, player_id in red_rows:
                before_time = max(0, red_time - 1)
                after_time = red_time + 1
                before = {player for start, end, player in rows if start <= before_time < end}
                after = {player for start, end, player in rows if start <= after_time < end}
                if player_id in before and len(after) >= len(before):
                    red_no_raw_drop.append((key, red_time, player_id, len(before), len(after)))

        def describe(items):
            described = []
            for (match_id, side), time, count in items[:max_examples]:
                described.append(
                    {
                        "match": match_labels.get(match_id, str(match_id)),
                        "side": side,
                        "time": f"{time // 60}:{time % 60:02d}",
                        "active_count": count,
                    }
                )
            return described

        self.stdout.write(f"teams_checked={len(intervals_by_team)}")
        self.stdout.write(f"invalid_intervals={len(invalid_intervals)}")
        self.stdout.write(f"exact_duplicate_intervals={sum(1 for count in exact_duplicates.values() if count > 1)}")
        self.stdout.write(f"player_interval_overlaps={len(player_overlaps)}")
        self.stdout.write(f"active_at_0_distribution={dict(sorted(active_at_zero.items()))}")
        self.stdout.write(f"max_raw_active={max_raw}")
        self.stdout.write(f"raw_over_11_count={len(raw_over_11)}")
        self.stdout.write(f"raw_over_11_examples={describe(raw_over_11)}")
        self.stdout.write(f"max_discipline_adjusted_active={max_adjusted}")
        self.stdout.write(f"discipline_adjusted_over_11_count={len(adjusted_over_11)}")
        self.stdout.write(f"discipline_adjusted_over_11_examples={describe(adjusted_over_11)}")
        self.stdout.write(f"red_events_checked={sum(len(rows) for rows in sent_off_by_team.values())}")
        self.stdout.write(f"red_events_without_raw_interval_drop={len(red_no_raw_drop)}")
        self.stdout.write(f"red_no_raw_drop_examples={red_no_raw_drop[:max_examples]}")
        self.stdout.write(f"low_active_segments_ge60s_under10={len(low_active_segments)}")
        self.stdout.write(f"low_active_examples={low_active_segments[:max_examples]}")
