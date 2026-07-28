import ExcelJS from 'exceljs';
import type { TeamLineupContext, PlayerRole } from '../types/lineup';
import {
  ROLE_ORDER,
  ROLE_LABEL,
  BRAND,
  ALL_BORDERS,
  styleHeaderCell,
  styleRoleCell,
  downloadWorkbook,
  slug,
} from './xlsx';

// Export a single team's roster to a clean, vfoot-styled xlsx: role sections
// (Portieri/Difensori/Centrocampisti/Attaccanti), one player per row, with club,
// price, media voto puro and appearances. A totals row closes the sheet.
export async function downloadRosterXlsx(ctx: TeamLineupContext): Promise<void> {
  const wb = new ExcelJS.Workbook();
  wb.creator = 'Vfoot Boosted';
  const ws = wb.addWorksheet('Rosa', { views: [{ state: 'frozen', ySplit: 3 }] });

  const columns = [
    { header: 'Giocatore', width: 26 },
    { header: 'Club', width: 18 },
    { header: 'Ruolo', width: 8 },
    { header: 'Prezzo', width: 10 },
    { header: 'Media voto puro', width: 16 },
    { header: 'Presenze', width: 10 },
  ];

  // Title row (merged), league/team context.
  ws.mergeCells(1, 1, 1, columns.length);
  const title = ws.getCell(1, 1);
  title.value = `Rosa · ${ctx.team.name}`;
  title.font = { bold: true, size: 14, color: { argb: BRAND.ink } };
  ws.mergeCells(2, 1, 2, columns.length);
  const sub = ws.getCell(2, 1);
  sub.value = `${ctx.roster.length} giocatori${ctx.stats_season ? ` · media voto ${ctx.stats_season}` : ''}`;
  sub.font = { size: 10, color: { argb: 'FF64748B' } };

  // Header row.
  const headerRowIdx = 3;
  columns.forEach((c, i) => {
    const cell = ws.getCell(headerRowIdx, i + 1);
    cell.value = c.header;
    styleHeaderCell(cell);
    ws.getColumn(i + 1).width = c.width;
  });

  let r = headerRowIdx + 1;
  let totalSpent = 0;

  for (const role of ROLE_ORDER) {
    const players = ctx.roster
      .filter((p) => p.role === role)
      .sort((a, b) => b.price - a.price);
    if (!players.length) continue;

    // Role band.
    ws.mergeCells(r, 1, r, columns.length);
    const band = ws.getCell(r, 1);
    band.value = `${ROLE_LABEL[role as PlayerRole]} (${players.length})`;
    styleRoleCell(band);
    r += 1;

    for (const p of players) {
      totalSpent += p.price || 0;
      const row = ws.getRow(r);
      row.getCell(1).value = p.name;
      row.getCell(2).value = p.real_team ?? '';
      row.getCell(3).value = role;
      row.getCell(4).value = p.price ?? 0;
      row.getCell(5).value = p.value ?? null;
      row.getCell(6).value = p.appearances ?? 0;
      row.getCell(4).numFmt = '0';
      row.getCell(5).numFmt = '0.00';
      for (let c = 1; c <= columns.length; c += 1) row.getCell(c).border = ALL_BORDERS;
      // Zebra banding for readability.
      if (r % 2 === 0) {
        for (let c = 1; c <= columns.length; c += 1) {
          row.getCell(c).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: BRAND.band } };
        }
      }
      r += 1;
    }
  }

  // Totals row.
  const totalRow = ws.getRow(r + 1);
  totalRow.getCell(1).value = 'Totale speso';
  totalRow.getCell(1).font = { bold: true };
  totalRow.getCell(4).value = totalSpent;
  totalRow.getCell(4).numFmt = '0';
  totalRow.getCell(4).font = { bold: true };

  await downloadWorkbook(wb, `rosa_${slug(ctx.team.name)}`);
}
