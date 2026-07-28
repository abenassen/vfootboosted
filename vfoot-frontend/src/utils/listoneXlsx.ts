import ExcelJS from 'exceljs';
import type { ChampionshipPlayersResponse, ChampionshipPlayer } from '../types/realChampionship';
import {
  BRAND,
  ALL_BORDERS,
  styleHeaderCell,
  downloadWorkbook,
  slug,
} from './xlsx';

// Listone export (#13): one "complessivo" sheet the admin can fill in — each row
// has the player_id, a per-player TEAM dropdown ("Assegnato a") and a price — plus
// read-only per-role reference sheets. The filled complessivo sheet can be
// re-uploaded to assign rosters in one shot (backend parses player_id + team + price).
//
// Editable sheet name + header labels below are a contract with the backend
// importer (roster_xlsx.py): keep them in sync.
export const LISTONE_SHEET = 'Listone';
export const COL_PLAYER_ID = 'player_id';
export const COL_ASSIGNED = 'Assegnato a';
export const COL_PRICE = 'Prezzo';

// Listone role codes are Italian (POR/DIF/CEN/ATT), distinct from the lineup codes.
const LISTONE_ROLE_ORDER = ['POR', 'DIF', 'CEN', 'ATT'] as const;
const LISTONE_ROLE_LABEL: Record<string, string> = {
  POR: 'Portieri',
  DIF: 'Difensori',
  CEN: 'Centrocampisti',
  ATT: 'Attaccanti',
};

type Col = { key: string; header: string; width: number; numFmt?: string };

// Columns shared by the complessivo sheet and the per-role sheets. The complessivo
// sheet adds the editable "Assegnato a" + "Prezzo" columns after these.
const BASE_COLS: Col[] = [
  { key: COL_PLAYER_ID, header: COL_PLAYER_ID, width: 10, numFmt: '0' },
  { key: 'name', header: 'Giocatore', width: 26 },
  { key: 'role', header: 'Ruolo', width: 8 },
  { key: 'team', header: 'Club', width: 18 },
  { key: 'value', header: 'Media voto puro', width: 16, numFmt: '0.00' },
  { key: 'market', header: 'Mercato', width: 12, numFmt: '0' },
  { key: 'owner', header: 'Proprietario attuale', width: 20 },
];

function cellValue(p: ChampionshipPlayer, key: string): string | number | null {
  switch (key) {
    case COL_PLAYER_ID:
      return p.player_id;
    case 'name':
      return p.name;
    case 'role':
      return p.role || '';
    case 'team':
      return p.team ?? '';
    case 'value':
      return p.estimated_value ?? p.value ?? null;
    case 'market':
      return p.market_value ?? null;
    case 'owner':
      return p.owner ?? '';
    default:
      return null;
  }
}

function writeHeader(ws: ExcelJS.Worksheet, cols: Col[]): void {
  cols.forEach((c, i) => {
    const cell = ws.getCell(1, i + 1);
    cell.value = c.header;
    styleHeaderCell(cell);
    ws.getColumn(i + 1).width = c.width;
  });
  ws.views = [{ state: 'frozen', ySplit: 1 }];
}

function writeRows(ws: ExcelJS.Worksheet, cols: Col[], players: ChampionshipPlayer[], startRow: number): void {
  players.forEach((p, idx) => {
    const r = startRow + idx;
    const row = ws.getRow(r);
    cols.forEach((c, i) => {
      const cell = row.getCell(i + 1);
      cell.value = cellValue(p, c.key);
      if (c.numFmt) cell.numFmt = c.numFmt;
      cell.border = ALL_BORDERS;
      if (r % 2 === 0) cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: BRAND.band } };
    });
  });
}

export async function downloadListoneXlsx(
  data: ChampionshipPlayersResponse,
  teamNames: string[],
  leagueName: string,
): Promise<void> {
  const wb = new ExcelJS.Workbook();
  wb.creator = 'Vfoot Boosted';

  // Only assignable players (a role decided) can be dropped into a roster; still
  // list everyone in the reference sheets, but sort the complessivo by role then value.
  const all = [...data.players].sort((a, b) => {
    const ra = LISTONE_ROLE_ORDER.indexOf(a.role as never);
    const rb = LISTONE_ROLE_ORDER.indexOf(b.role as never);
    if (ra !== rb) return (ra < 0 ? 99 : ra) - (rb < 0 ? 99 : rb);
    return (b.estimated_value ?? b.value ?? -1) - (a.estimated_value ?? a.value ?? -1);
  });

  // --- Hidden sheet holding the team names, referenced by the dropdown. Using a
  // range reference (not an inline list) avoids the ~255-char inline-formula limit. ---
  const teamsSheet = wb.addWorksheet('_Squadre');
  teamsSheet.state = 'veryHidden';
  teamNames.forEach((name, i) => {
    teamsSheet.getCell(i + 1, 1).value = name;
  });
  const teamsRef =
    teamNames.length > 0 ? `_Squadre!$A$1:$A$${teamNames.length}` : null;

  // --- Complessivo (editable) sheet ---
  const editCols: Col[] = [
    ...BASE_COLS,
    { key: COL_ASSIGNED, header: COL_ASSIGNED, width: 20 },
    { key: COL_PRICE, header: COL_PRICE, width: 10, numFmt: '0' },
  ];
  const ws = wb.addWorksheet(LISTONE_SHEET, { views: [{ state: 'frozen', ySplit: 2 }] });

  // Instruction row 1 (merged), header on row 2.
  ws.mergeCells(1, 1, 1, editCols.length);
  const instr = ws.getCell(1, 1);
  instr.value =
    'Compila "Assegnato a" (menu a discesa) e "Prezzo", poi ricarica questo file in Gestione lega → Roster per assegnare le rose.';
  instr.font = { italic: true, size: 10, color: { argb: 'FF64748B' } };

  editCols.forEach((c, i) => {
    const cell = ws.getCell(2, i + 1);
    cell.value = c.header;
    styleHeaderCell(cell);
    ws.getColumn(i + 1).width = c.width;
  });

  const assignedColIdx = BASE_COLS.length + 1; // 1-based
  const priceColIdx = BASE_COLS.length + 2;
  const firstDataRow = 3;

  all.forEach((p, idx) => {
    const r = firstDataRow + idx;
    const row = ws.getRow(r);
    BASE_COLS.forEach((c, i) => {
      const cell = row.getCell(i + 1);
      cell.value = cellValue(p, c.key);
      if (c.numFmt) cell.numFmt = c.numFmt;
      cell.border = ALL_BORDERS;
      if (r % 2 === 0) cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: BRAND.band } };
    });
    // Pre-fill the current owner so a partial roster round-trips without loss.
    const assignedCell = row.getCell(assignedColIdx);
    assignedCell.value = p.owner ?? null;
    assignedCell.border = ALL_BORDERS;
    const priceCell = row.getCell(priceColIdx);
    priceCell.numFmt = '0';
    priceCell.border = ALL_BORDERS;
    if (r % 2 === 0) {
      assignedCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: BRAND.band } };
      priceCell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: BRAND.band } };
    }
    // Team dropdown.
    if (teamsRef) {
      assignedCell.dataValidation = {
        type: 'list',
        allowBlank: true,
        formulae: [`=${teamsRef}`],
        showErrorMessage: true,
        errorStyle: 'stop',
        error: 'Scegli una squadra dall’elenco (o lascia vuoto per svincolato).',
      };
    }
  });

  // --- Per-role reference sheets (read-only view) ---
  for (const role of LISTONE_ROLE_ORDER) {
    const players = all.filter((p) => p.role === role);
    if (!players.length) continue;
    const rs = wb.addWorksheet(LISTONE_ROLE_LABEL[role]);
    writeHeader(rs, BASE_COLS);
    writeRows(rs, BASE_COLS, players, 2);
  }

  await downloadWorkbook(wb, `listone_${slug(leagueName)}`);
}
