/**
 * Contract tests: the frontend's idea of a payload must match what the backend
 * actually sends.
 *
 * This file exists because of a bug that two independent reviews found on the
 * same day. The scoreboard declared nine fields; the API sent six different
 * ones. Neither side was wrong on its own terms, and 62 passing tests plus a
 * green `tsc` and a green `next build` all missed it — because nothing ever
 * compared the two. What the landing page rendered was a fabricated `0.00%`
 * (from `total_return ?? 0`) and a `NaN%` (from a `!== null` check that
 * `undefined` walks straight through), for the only two numbers this project
 * is judged by.
 *
 * The fixtures here are the *real* committed artefacts, not hand-written
 * samples, so a change to the data pipeline shows up here rather than on the
 * dashboard.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const REPO_ROOT = join(__dirname, '..', '..', '..');

function readJson(relativePath: string): any {
  return JSON.parse(readFileSync(join(REPO_ROOT, relativePath), 'utf8'));
}

describe('promotion board contract', () => {
  // Mirrors the EdgeRecord interface in components/EdgeScoreboard.tsx. Keep the
  // two in step: this list is the whole point of the file.
  const REQUIRED_FIELDS = [
    'strategy',
    'instrument',
    'domain',
    'approved',
    'role',
    'win_rate',
    'mean_excess_pct',
    't_stat',
    // The cluster-robust fields. `n` alone cannot distinguish 40,768 events over
    // 125 independent weeks from 245 events over 13, and the scoreboard now shows
    // both — so both have to be present on every row, including failed ones.
    't_stat_iid',
    'n_clusters',
    'cluster_by',
    // Evidence expires. The board records the *boundary* of the study and the
    // declared shelf life; the age itself is computed per-request by
    // PromotionRecord, because a file that must rebuild to identical bytes cannot
    // hold a number that changes at midnight.
    'evidence_end',
    'max_evidence_age_days',
    'n',
    'implementation',
    'evidence',
    'failed',
  ] as const;

  const board = readJson('data/promotion_board.json');

  it('the committed board has rows to render', () => {
    expect(Array.isArray(board.board)).toBe(true);
    expect(board.board.length).toBeGreaterThan(0);
  });

  it('no approved row rests on an i.i.d. t-statistic', () => {
    // The defect this guards: both trade edges cleared a 3.77 hurdle with t=5.40
    // and t=6.38 computed as if their overlapping event windows were independent
    // draws. Clustered, the same data gives 2.35 and 1.81.
    expect(board.inference).toBe('cluster_robust');
    for (const row of board.board) {
      if (!row.approved) continue;
      expect(row.inference, `${row.strategy} was approved without clustered inference`).toBe(
        'cluster_robust',
      );
      expect(row.n_clusters, `${row.strategy} has too few independent units`).toBeGreaterThanOrEqual(
        board.min_clusters,
      );
    }
  });

  it('every field the scoreboard reads exists on every row', () => {
    for (const row of board.board) {
      for (const field of REQUIRED_FIELDS) {
        expect(
          row,
          `row ${row.strategy} is missing "${field}" — the scoreboard would render it as a fabricated value`,
        ).toHaveProperty(field);
      }
    }
  });

  it('role is always an explicit trade/avoid, never blank', () => {
    for (const row of board.board) {
      expect(['trade', 'avoid']).toContain(row.role);
    }
  });

  it('mean_excess_pct is a percent, not a fraction', () => {
    // -2.08 means -2.08%. If this ever becomes -0.0208 the scoreboard silently
    // renders -0.02% and the edge looks a hundred times weaker than it is.
    const approved = board.board.filter((r: any) => r.approved);
    expect(approved.length).toBeGreaterThan(0);
    for (const row of approved) {
      expect(typeof row.mean_excess_pct).toBe('number');
      expect(Math.abs(row.mean_excess_pct)).toBeGreaterThan(0.01);
    }
  });

  it('win_rate is a fraction in [0, 1]', () => {
    for (const row of board.board.filter((r: any) => r.approved)) {
      expect(row.win_rate).toBeGreaterThan(0);
      expect(row.win_rate).toBeLessThan(1);
    }
  });

  it('an approved avoid row never claims to be tradable', () => {
    const avoid = board.board.filter((r: any) => r.approved && r.role === 'avoid');
    for (const row of avoid) {
      // Avoidance filters are negative-drift findings. If one ever shows a
      // positive mean excess return, the role label and the data disagree.
      expect(row.mean_excess_pct).toBeLessThan(0);
    }
  });

  it('the tradable count the badge shows matches the board itself', () => {
    const tradable = board.board.filter((r: any) => r.approved && r.role === 'trade');
    expect(tradable.length).toBe(board.counts.approved_trade);
  });

  it('every implementation string has a label in the scoreboard', () => {
    // A missing label renders a blank badge instead of the direction of the
    // trade — which for an edge that is short-only is the whole meaning.
    const source = readFileSync(
      join(__dirname, '..', 'components', 'EdgeScoreboard.tsx'),
      'utf8',
    );
    for (const row of board.board.filter((r: any) => r.approved)) {
      expect(source, `IMPLEMENTATION_LABEL has no entry for "${row.implementation}"`).toContain(
        row.implementation,
      );
    }
  });
});
