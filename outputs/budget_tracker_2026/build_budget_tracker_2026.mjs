import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "C:/Users/toanvuvv/Desktop/BysCom/App Rep Comment/outputs/budget_tracker_2026";
const outputPath = path.join(outputDir, "Monthly Budget Tracker 2026.xlsx");

const workbook = Workbook.create();

const months = [
  { short: "Jan", full: "January", col: "D" },
  { short: "Feb", full: "February", col: "E" },
  { short: "Mar", full: "March", col: "F" },
  { short: "Apr", full: "April", col: "G" },
  { short: "May", full: "May", col: "H" },
  { short: "Jun", full: "June", col: "I" },
  { short: "Jul", full: "July", col: "J" },
  { short: "Aug", full: "August", col: "K" },
  { short: "Sep", full: "September", col: "L" },
  { short: "Oct", full: "October", col: "M" },
  { short: "Nov", full: "November", col: "N" },
  { short: "Dec", full: "December", col: "O" },
];

const categories = [
  ["Income", "Salary", 6500],
  ["Income", "Side Income", 500],
  ["Income", "Other Income", 0],
  ["Expense", "Housing", 1800],
  ["Expense", "Utilities", 280],
  ["Expense", "Groceries", 850],
  ["Expense", "Transportation", 450],
  ["Expense", "Insurance", 300],
  ["Expense", "Debt Payments", 400],
  ["Expense", "Subscriptions", 120],
  ["Expense", "Health", 250],
  ["Expense", "Dining Out", 350],
  ["Expense", "Entertainment", 250],
  ["Expense", "Savings Transfer", 1000],
  ["Expense", "Miscellaneous", 300],
];

const colors = {
  navy: "#17324D",
  teal: "#0F766E",
  green: "#2F6B4F",
  amber: "#C47A1A",
  red: "#B42318",
  blue: "#2B5C8A",
  lightBlue: "#EAF2F8",
  lightTeal: "#E8F5F2",
  lightGreen: "#EAF5EF",
  lightAmber: "#FFF4E5",
  surface: "#F7F9FB",
  white: "#FFFFFF",
  gray: "#E3E8EF",
  darkText: "#22313F",
  mutedText: "#5B677A",
};

function quoteSheet(name) {
  return `'${name}'`;
}

function monthActualFormula(month, type, categoryRef = null) {
  const sheet = quoteSheet(month.short);
  if (categoryRef) {
    return `=SUMIFS(${sheet}!$E$11:$E$109,${sheet}!$C$11:$C$109,"${type}",${sheet}!$D$11:$D$109,${categoryRef})`;
  }
  return `=SUMIFS(${sheet}!$E$11:$E$109,${sheet}!$C$11:$C$109,"${type}")`;
}

function allMonthsActualFormula(type, categoryRef = null) {
  return "=" + months.map((month) => monthActualFormula(month, type, categoryRef).slice(1)).join("+");
}

function setWidths(sheet, widths) {
  for (const [col, px] of Object.entries(widths)) {
    sheet.getRange(`${col}1:${col}120`).format.columnWidthPx = px;
  }
}

function styleTitle(sheet, range, title, subtitle = "") {
  const titleRange = sheet.getRange(range);
  titleRange.merge();
  titleRange.values = [[title]];
  titleRange.format = {
    fill: colors.navy,
    font: { bold: true, color: colors.white, size: 18 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  titleRange.format.rowHeightPx = 34;
  if (subtitle) {
    const [start] = range.split(":");
    const subtitleCell = start.replace(/\d+$/, "2");
    const subtitleRange = sheet.getRange(`${subtitleCell}:${subtitleCell.replace(/^[A-Z]+/, range.split(":")[1].replace(/\d+$/, ""))}`);
    subtitleRange.merge();
    subtitleRange.values = [[subtitle]];
    subtitleRange.format = {
      fill: colors.lightBlue,
      font: { italic: true, color: colors.mutedText },
      horizontalAlignment: "center",
    };
  }
}

function styleHeader(range, fill = colors.teal) {
  range.format = {
    fill,
    font: { bold: true, color: colors.white },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
}

function styleBody(range) {
  range.format = {
    fill: colors.white,
    font: { color: colors.darkText },
    borders: { color: colors.gray, style: "continuous", weight: "thin" },
  };
}

function money(range) {
  range.format.numberFormat = "$#,##0;[Red]($#,##0);-";
}

function percent(range) {
  range.format.numberFormat = "0.0%";
}

function createCategoriesSheet() {
  const sheet = workbook.worksheets.add("Categories");
  sheet.showGridLines = false;
  styleTitle(sheet, "A1:P1", "2026 Budget Categories", "Edit category names and budgets here; monthly tabs and dashboard update automatically.");
  setWidths(sheet, {
    A: 110, B: 165, C: 120, D: 92, E: 92, F: 92, G: 92, H: 92, I: 92, J: 92, K: 92, L: 92, M: 92, N: 92, O: 92, P: 120,
  });

  sheet.getRange("A4:P4").values = [[
    "Type", "Category", "Monthly Default", ...months.map((m) => m.short), "Annual Budget",
  ]];
  styleHeader(sheet.getRange("A4:P4"), colors.teal);

  const rows = categories.map(([type, category, monthly]) => [
    type, category, monthly, ...months.map(() => monthly), null,
  ]);
  sheet.getRange(`A5:P${4 + rows.length}`).values = rows;
  sheet.getRange("P5").formulas = [["=SUM(D5:O5)"]];
  sheet.getRange(`P5:P${4 + rows.length}`).fillDown();

  styleBody(sheet.getRange(`A5:P${4 + rows.length}`));
  money(sheet.getRange(`C5:P${4 + rows.length}`));
  sheet.getRange(`A5:A${4 + rows.length}`).dataValidation = { rule: { type: "list", values: ["Income", "Expense"] } };
  sheet.freezePanes.freezeRows(4);
  sheet.tables.add(`A4:P${4 + rows.length}`, true, "BudgetCategories");

  sheet.getRange("A22:P22").merge();
  sheet.getRange("A22:P22").values = [[
    "Tip: add new categories by inserting rows above this note, then extend dashboard category formulas if you need them included in charts.",
  ]];
  sheet.getRange("A22:P22").format = {
    fill: colors.lightAmber,
    font: { color: colors.mutedText, italic: true },
    wrapText: true,
  };
}

function createMonthlySheet(month, idx) {
  const sheet = workbook.worksheets.add(month.short);
  sheet.showGridLines = false;
  styleTitle(sheet, "A1:H1", `${month.full} 2026 Transactions`, "Enter each income or expense once. Dashboard and summary tabs calculate from this table.");
  setWidths(sheet, { A: 95, B: 210, C: 95, D: 165, E: 125, F: 75, G: 210, H: 80, J: 140, K: 120 });

  sheet.getRange("A4:E4").merge();
  sheet.getRange("A4:E4").values = [["Monthly Snapshot"]];
  styleHeader(sheet.getRange("A4:E4"), colors.green);
  sheet.getRange("A5:E8").values = [
    ["Budget Income", "Actual Income", "Budget Expenses", "Actual Expenses", "Net Cash Flow"],
    [null, null, null, null, null],
    ["Transactions", "Paid Items", "Open Items", "Largest Expense", "Budget Remaining"],
    [null, null, null, null, null],
  ];
  styleHeader(sheet.getRange("A5:E5"), colors.blue);
  styleHeader(sheet.getRange("A7:E7"), colors.blue);
  styleBody(sheet.getRange("A6:E6"));
  styleBody(sheet.getRange("A8:E8"));
  sheet.getRange("A6:E6").formulas = [[
    `=SUMIFS(Categories!$${month.col}$5:$${month.col}$19,Categories!$A$5:$A$19,"Income")`,
    `=SUMIFS($E$11:$E$109,$C$11:$C$109,"Income")`,
    `=SUMIFS(Categories!$${month.col}$5:$${month.col}$19,Categories!$A$5:$A$19,"Expense")`,
    `=SUMIFS($E$11:$E$109,$C$11:$C$109,"Expense")`,
    "=B6-D6",
  ]];
  sheet.getRange("A8:E8").formulas = [[
    "=COUNTA(A11:A109)",
    '=COUNTIFS(F11:F109,"Yes",A11:A109,"<>")',
    '=COUNTIFS(F11:F109,"No",A11:A109,"<>")',
    '=IFERROR(MAXIFS(E11:E109,C11:C109,"Expense"),0)',
    "=C6-D6",
  ]];
  money(sheet.getRange("A6:E6"));
  money(sheet.getRange("D8:E8"));

  sheet.getRange("A10:H10").values = [["Date", "Description", "Type", "Category", "Amount", "Paid?", "Notes", "Month"]];
  styleHeader(sheet.getRange("A10:H10"), colors.teal);
  const entryRows = Array.from({ length: 99 }, () => [null, null, null, null, null, null, null, month.short]);
  sheet.getRange("A11:H109").values = entryRows;
  styleBody(sheet.getRange("A11:H109"));
  sheet.getRange("A11:A109").format.numberFormat = "yyyy-mm-dd";
  money(sheet.getRange("E11:E109"));
  sheet.getRange("C11:C109").dataValidation = { rule: { type: "list", values: ["Income", "Expense"] } };
  sheet.getRange("D11:D109").dataValidation = { rule: { type: "list", formula1: "Categories!$B$5:$B$19" } };
  sheet.getRange("F11:F109").dataValidation = { rule: { type: "list", values: ["Yes", "No"] } };
  sheet.tables.add("A10:H109", true, `${month.short}Transactions`);

  if (idx === 0) {
    sheet.getRange("A11:H15").values = [
      [new Date(2026, 0, 1), "Paycheck", "Income", "Salary", 6500, "Yes", "Example row; replace with your real data", month.short],
      [new Date(2026, 0, 2), "Rent", "Expense", "Housing", 1800, "Yes", "Example row", month.short],
      [new Date(2026, 0, 7), "Groceries", "Expense", "Groceries", 210, "Yes", "Example row", month.short],
      [new Date(2026, 0, 12), "Utilities", "Expense", "Utilities", 175, "No", "Example row", month.short],
      [new Date(2026, 0, 20), "Dinner", "Expense", "Dining Out", 85, "Yes", "Example row", month.short],
    ];
  }

  sheet.getRange("A3:H3").format = { fill: colors.surface };
  sheet.freezePanes.freezeRows(10);
}

function createAnnualSummary() {
  const sheet = workbook.worksheets.add("Annual Summary");
  sheet.showGridLines = false;
  styleTitle(sheet, "A1:H1", "2026 Annual Summary", "Formula-backed month-by-month totals from each transaction sheet.");
  setWidths(sheet, { A: 110, B: 120, C: 120, D: 130, E: 130, F: 125, G: 130, H: 105 });
  sheet.getRange("A4:H4").values = [[
    "Month", "Budget Income", "Actual Income", "Budget Expenses", "Actual Expenses", "Net Cash Flow", "Expense Variance", "Savings Rate",
  ]];
  styleHeader(sheet.getRange("A4:H4"), colors.teal);
  sheet.getRange("A5:A16").values = months.map((m) => [m.full]);
  sheet.getRange("B5:H16").formulas = months.map((m, idx) => {
    const row = 5 + idx;
    return [
      `=SUMIFS(Categories!$${m.col}$5:$${m.col}$19,Categories!$A$5:$A$19,"Income")`,
      monthActualFormula(m, "Income"),
      `=SUMIFS(Categories!$${m.col}$5:$${m.col}$19,Categories!$A$5:$A$19,"Expense")`,
      monthActualFormula(m, "Expense"),
      `=C${row}-E${row}`,
      `=D${row}-E${row}`,
      `=IF(C${row}=0,"",F${row}/C${row})`,
    ];
  });
  sheet.getRange("A17:H17").values = [["Total", null, null, null, null, null, null, null]];
  sheet.getRange("B17:H17").formulas = [[
    "=SUM(B5:B16)", "=SUM(C5:C16)", "=SUM(D5:D16)", "=SUM(E5:E16)", "=SUM(F5:F16)", "=SUM(G5:G16)", '=IF(C17=0,"",F17/C17)',
  ]];
  styleBody(sheet.getRange("A5:H17"));
  sheet.getRange("A17:H17").format = { fill: colors.lightTeal, font: { bold: true, color: colors.darkText } };
  money(sheet.getRange("B5:G17"));
  percent(sheet.getRange("H5:H17"));
  sheet.tables.add("A4:H17", true, "AnnualSummary");
  sheet.freezePanes.freezeRows(4);
}

function createDashboard() {
  const sheet = workbook.worksheets.add("Dashboard");
  sheet.showGridLines = false;
  styleTitle(sheet, "A1:L1", "2026 Monthly Budget Dashboard", "Live overview from budget categories and monthly transaction tabs.");
  setWidths(sheet, { A: 120, B: 115, C: 115, D: 115, E: 30, F: 120, G: 115, H: 115, I: 30, J: 130, K: 115, L: 115 });

  const cards = [
    ["A4:D4", "A5:D6", "Actual Income", "='Annual Summary'!C17", "$#,##0"],
    ["F4:H4", "F5:H6", "Actual Expenses", "='Annual Summary'!E17", "$#,##0"],
    ["J4:L4", "J5:L6", "Net Cash Flow", "='Annual Summary'!F17", "$#,##0"],
    ["A8:D8", "A9:D10", "Budgeted Expenses", "='Annual Summary'!D17", "$#,##0"],
    ["F8:H8", "F9:H10", "Budget Remaining", "='Annual Summary'!G17", "$#,##0"],
    ["J8:L8", "J9:L10", "Savings Rate", '=IF(\'Annual Summary\'!C17=0,"",\'Annual Summary\'!F17/\'Annual Summary\'!C17)', "0.0%"],
  ];
  for (const [labelRange, valueRange, label, formula, format] of cards) {
    const lr = sheet.getRange(labelRange);
    const vr = sheet.getRange(valueRange);
    lr.merge();
    vr.merge();
    lr.values = [[label]];
    vr.formulas = [[formula]];
    const cardFill = valueRange.startsWith("J5") || valueRange.startsWith("F9") ? colors.lightGreen : colors.lightBlue;
    lr.format = {
      fill: cardFill,
      font: { bold: true, color: colors.mutedText, size: 10 },
      horizontalAlignment: "center",
      verticalAlignment: "center",
      borders: { color: colors.gray, style: "continuous", weight: "thin" },
    };
    vr.format = {
      fill: cardFill,
      font: { bold: true, color: colors.navy, size: 16 },
      horizontalAlignment: "center",
      verticalAlignment: "center",
      numberFormat: format,
      borders: { color: colors.gray, style: "continuous", weight: "thin" },
    };
    vr.format.rowHeightPx = 56;
  }

  sheet.getRange("A13:D13").values = [["Toản", "Annual Budget", "Actual Spend", "Remaining"]];
  styleHeader(sheet.getRange("A13:D13"), colors.green);
  const expenseCategories = categories.filter(([type]) => type === "Expense").map(([, category]) => category);
  sheet.getRange(`A14:A${13 + expenseCategories.length}`).values = expenseCategories.map((c) => [c]);
  sheet.getRange(`B14:D${13 + expenseCategories.length}`).formulas = expenseCategories.map((_, i) => {
    const row = 14 + i;
    return [
      `=SUMIFS(Categories!$P$5:$P$19,Categories!$B$5:$B$19,A${row})`,
      allMonthsActualFormula("Expense", `A${row}`),
      `=B${row}-C${row}`,
    ];
  });
  styleBody(sheet.getRange(`A14:D${13 + expenseCategories.length}`));
  money(sheet.getRange(`B14:D${13 + expenseCategories.length}`));
  sheet.tables.add(`A13:D${13 + expenseCategories.length}`, true, "DashboardExpenseCategories");

  sheet.getRange("F13:H13").values = [["Month", "Income", "Expenses"]];
  styleHeader(sheet.getRange("F13:H13"), colors.blue);
  sheet.getRange("F14:F25").formulas = months.map((_, idx) => [`='Annual Summary'!A${5 + idx}`]);
  sheet.getRange("G14:H25").formulas = months.map((_, idx) => [[`='Annual Summary'!C${5 + idx}`, `='Annual Summary'!E${5 + idx}`][0], [`='Annual Summary'!C${5 + idx}`, `='Annual Summary'!E${5 + idx}`][1]]);
  styleBody(sheet.getRange("F14:H25"));
  money(sheet.getRange("G14:H25"));

  sheet.getRange("J13:L13").values = [["Category", "Actual Spend", "Share"]];
  styleHeader(sheet.getRange("J13:L13"), colors.blue);
  sheet.getRange("J14:K25").formulas = expenseCategories.map((_, idx) => {
    const sourceRow = 14 + idx;
    return [`=A${sourceRow}`, `=C${sourceRow}`];
  });
  sheet.getRange("L14:L25").formulas = expenseCategories.map((_, idx) => [`=IF(SUM($K$14:$K$25)=0,"",K${14 + idx}/SUM($K$14:$K$25))`]);
  styleBody(sheet.getRange("J14:L25"));
  money(sheet.getRange("K14:K25"));
  percent(sheet.getRange("L14:L25"));

  const trend = sheet.charts.add("line", sheet.getRange("F13:H25"));
  trend.title = "Monthly Income vs. Expenses";
  trend.hasLegend = true;
  trend.xAxis = { axisType: "textAxis" };
  trend.yAxis = { numberFormatCode: "$#,##0" };
  trend.setPosition("F28", "L44");

  const catChart = sheet.charts.add("bar", sheet.getRange("J13:K25"));
  catChart.title = "Expense Spend by Category";
  catChart.hasLegend = false;
  catChart.xAxis = { axisType: "textAxis" };
  catChart.yAxis = { numberFormatCode: "$#,##0" };
  catChart.setPosition("A28", "E44");

  sheet.getRange("A46:L46").merge();
  sheet.getRange("A46:L46").values = [["Workbook guide: update the Categories tab for planned budgets, then enter transactions on each monthly tab. Use Paid? to track open items."]];
  sheet.getRange("A46:L46").format = {
    fill: colors.lightAmber,
    font: { italic: true, color: colors.mutedText },
    wrapText: true,
  };
}

function createChecks() {
  const sheet = workbook.worksheets.add("Checks");
  sheet.showGridLines = false;
  styleTitle(sheet, "A1:E1", "Workbook Checks", "Formula checks to confirm dashboard values reconcile to annual summary.");
  setWidths(sheet, { A: 230, B: 145, C: 145, D: 105, E: 240 });
  sheet.getRange("A4:E4").values = [["Check", "Dashboard Value", "Source Value", "Status", "Notes"]];
  styleHeader(sheet.getRange("A4:E4"), colors.teal);
  sheet.getRange("A5:E9").values = [
    ["Actual income ties", null, null, null, "Dashboard income equals Annual Summary actual income."],
    ["Actual expenses ties", null, null, null, "Dashboard expenses equals Annual Summary actual expenses."],
    ["Net cash flow ties", null, null, null, "Dashboard net cash flow equals Annual Summary net cash flow."],
    ["Budget remaining ties", null, null, null, "Dashboard budget remaining equals Annual Summary expense variance."],
    ["Savings rate ties", null, null, null, "Dashboard savings rate equals annual savings rate."],
  ];
  sheet.getRange("B5:D9").formulas = [
    ["=Dashboard!A5", "='Annual Summary'!C17", '=IF(ABS(B5-C5)<0.01,"OK","Review")'],
    ["=Dashboard!F5", "='Annual Summary'!E17", '=IF(ABS(B6-C6)<0.01,"OK","Review")'],
    ["=Dashboard!J5", "='Annual Summary'!F17", '=IF(ABS(B7-C7)<0.01,"OK","Review")'],
    ["=Dashboard!F9", "='Annual Summary'!G17", '=IF(ABS(B8-C8)<0.01,"OK","Review")'],
    ["=Dashboard!J9", "='Annual Summary'!H17", '=IF(ABS(B9-C9)<0.0001,"OK","Review")'],
  ];
  styleBody(sheet.getRange("A5:E9"));
  money(sheet.getRange("B5:C8"));
  percent(sheet.getRange("B9:C9"));
  sheet.getRange("D5:D9").format = { fill: colors.lightGreen, font: { bold: true, color: colors.green }, horizontalAlignment: "center" };
}

createDashboard();
createCategoriesSheet();
months.forEach(createMonthlySheet);
createAnnualSummary();
createChecks();

await fs.mkdir(outputDir, { recursive: true });

const keyDashboard = await workbook.inspect({
  kind: "table",
  range: "Dashboard!A1:L46",
  include: "values,formulas",
  tableMaxRows: 18,
  tableMaxCols: 12,
  maxChars: 8000,
});
console.log("DASHBOARD_INSPECT");
console.log(keyDashboard.ndjson);

const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
  maxChars: 4000,
});
console.log("FORMULA_ERRORS");
console.log(formulaErrors.ndjson);

for (const sheetName of ["Dashboard", "Categories", ...months.map((m) => m.short), "Annual Summary", "Checks"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, `${sheetName.replace(/\s+/g, "_").toLowerCase()}_preview.png`), new Uint8Array(await preview.arrayBuffer()));
}

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
console.log(`EXPORTED:${outputPath}`);
