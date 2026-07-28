import ExcelJS from 'exceljs';
import type { PlayerRole } from '../types/lineup';

// Shared spreadsheet helpers (ExcelJS, fully client-side — nothing runs on the
// server, so this stays Linode-safe). Used by the roster export (Squadra) and the
// listone export (which also embeds per-cell dropdowns for offline roster filling).

export const ROLE_ORDER: PlayerRole[] = ['GK', 'DEF', 'MID', 'ATT'];
export const ROLE_LABEL: Record<PlayerRole, string> = {
  GK: 'Portieri',
  DEF: 'Difensori',
  MID: 'Centrocampisti',
  ATT: 'Attaccanti',
};

// vfoot brand-ish palette (ARGB, no leading #).
export const BRAND = {
  ink: 'FF0F172A', // slate-900
  headerBg: 'FF0F172A',
  headerText: 'FFFFFFFF',
  roleBg: 'FFE2E8F0', // slate-200
  band: 'FFF8FAFC', // slate-50 zebra
  border: 'FFCBD5E1', // slate-300
};

const thin = { style: 'thin' as const, color: { argb: BRAND.border } };
export const ALL_BORDERS = { top: thin, left: thin, bottom: thin, right: thin };

/** Style a header row cell (dark background, white bold text). */
export function styleHeaderCell(cell: ExcelJS.Cell): void {
  cell.font = { bold: true, color: { argb: BRAND.headerText }, size: 11 };
  cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: BRAND.headerBg } };
  cell.alignment = { vertical: 'middle', horizontal: 'left' };
  cell.border = ALL_BORDERS;
}

/** A full-width role band row (e.g. "Difensori"). */
export function styleRoleCell(cell: ExcelJS.Cell): void {
  cell.font = { bold: true, color: { argb: BRAND.ink }, size: 11 };
  cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: BRAND.roleBg } };
  cell.alignment = { vertical: 'middle', horizontal: 'left' };
}

/** Trigger a browser download of a finished workbook. */
export async function downloadWorkbook(wb: ExcelJS.Workbook, filename: string): Promise<void> {
  const buf = await wb.xlsx.writeBuffer();
  const blob = new Blob([buf], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Give the click a tick before revoking, then free the blob.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Safe filename fragment from an arbitrary label. */
export function slug(s: string): string {
  return (
    (s || 'vfoot')
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .replace(/[^a-zA-Z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'vfoot'
  );
}
