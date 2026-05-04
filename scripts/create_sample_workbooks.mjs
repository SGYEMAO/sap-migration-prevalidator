import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const artifactToolPath = require.resolve("@oai/artifact-tool");
const { SpreadsheetFile, Workbook } = await import(pathToFileURL(artifactToolPath).href);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, "..");

const workbooks = [
  {
    output: path.join(root, "mappings", "MATERIAL_MASTER", "uom_mapping.xlsx"),
    sheets: {
      Sheet1: [
        ["LegacyUoM", "SAPUoM", "Active", "Comment"],
        ["Each", "EA", "Y", "legacy text unit"],
        ["PCS", "PC", "Y", "pieces"],
        ["KG", "KG", "Y", "already aligned"],
      ],
    },
  },
  {
    output: path.join(root, "mappings", "MATERIAL_MASTER", "plant_mapping.xlsx"),
    sheets: {
      Sheet1: [
        ["LegacyPlant", "SAPPlant", "Active", "Comment"],
        ["SG01", "1000", "Y", "Singapore plant"],
        ["SG02", "1100", "Y", "Backup plant"],
      ],
    },
  },
  {
    output: path.join(root, "mappings", "MATERIAL_MASTER", "material_type_mapping.xlsx"),
    sheets: {
      Sheet1: [
        ["LegacyMaterialType", "SAPMaterialType", "Active", "Comment"],
        ["Finished", "FERT", "Y", "finished goods"],
        ["Raw", "ROH", "Y", "raw material"],
      ],
    },
  },
  {
    output: path.join(root, "mappings", "BP_CUSTOMER", "country_mapping.xlsx"),
    sheets: {
      Sheet1: [
        ["LegacyCountry", "SAPCountry", "Active", "Comment"],
        ["Singapore", "SG", "Y", "country text to ISO code"],
        ["United States", "US", "Y", "country text to ISO code"],
      ],
    },
  },
  {
    output: path.join(root, "mappings", "BP_CUSTOMER", "payment_terms_mapping.xlsx"),
    sheets: {
      Sheet1: [
        ["LegacyPaymentTerms", "SAPPaymentTerms", "Active", "Comment"],
        ["Net30", "0001", "Y", "example customer payment term"],
        ["Immediate", "0002", "Y", "example customer payment term"],
      ],
    },
  },
  {
    output: path.join(root, "mappings", "OPEN_PO", "vendor_mapping.xlsx"),
    sheets: {
      Sheet1: [
        ["LegacyVendor", "SAPVendor", "Active", "Comment"],
        ["VEND-001", "100000", "Y", "example vendor"],
        ["VEND-002", "100001", "Y", "example vendor"],
      ],
    },
  },
  {
    output: path.join(root, "mappings", "OPEN_PO", "purchasing_org_mapping.xlsx"),
    sheets: {
      Sheet1: [
        ["LegacyPurchasingOrg", "SAPPurchasingOrg", "Active", "Comment"],
        ["SGPO", "1000", "Y", "Singapore purchasing org"],
        ["MYPO", "2000", "Y", "Malaysia purchasing org"],
      ],
    },
  },
  {
    output: path.join(root, "sample_templates", "material_master_legacy_values_sample.xlsx"),
    sheets: {
      "Basic Data": [
        ["Material", "MaterialType", "BaseUoM"],
        ["MAT001", "Finished", "Each"],
        ["MAT002", "Raw", "PCS"],
        ["MAT003", "ROH", "BADUOM"],
      ],
      "Plant Data": [
        ["Material", "Plant", "StorageLocation"],
        ["MAT001", "SG01", "0001"],
        ["MAT002", "SG99", "0001"],
        ["MAT003", "SG02", "0001"],
      ],
      Contact: [
        ["Name", "OwnerEmail"],
        ["Data Owner", "migration.owner@example.com"],
      ],
    },
  },
];

async function buildWorkbook({ output, sheets }) {
  await fs.mkdir(path.dirname(output), { recursive: true });
  const workbook = Workbook.create();

  for (const [sheetName, rows] of Object.entries(sheets)) {
    const sheet = workbook.worksheets.add(sheetName);
    const rowCount = rows.length;
    const columnCount = rows[0].length;
    sheet.getRangeByIndexes(0, 0, rowCount, columnCount).values = rows;
    sheet.getRangeByIndexes(0, 0, 1, columnCount).format = {
      fill: "#1F4E78",
      font: { bold: true, color: "#FFFFFF" },
    };
    sheet.freezePanes.freezeRows(1);
    for (let column = 0; column < columnCount; column += 1) {
      const width = Math.min(
        Math.max(...rows.map((row) => String(row[column] ?? "").length)) * 8 + 28,
        220,
      );
      sheet.getRangeByIndexes(0, column, rowCount, 1).format.columnWidthPx = width;
    }
    await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  }

  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(output);
}

for (const workbookSpec of workbooks) {
  await buildWorkbook(workbookSpec);
}

console.log(`Created ${workbooks.length} workbook(s).`);
