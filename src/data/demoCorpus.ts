/**
 * SIH DEMO DATASET — deterministic synthetic investigation corpus.
 *
 * Every file references the SAME canonical identifiers so the uploaded graph
 * becomes meaningful: phones N-*, accounts A-*, vehicles V-*. These files are
 * pushed through the REAL Case Intake pipeline (upload -> parse -> process ->
 * materialize); nothing here bypasses ingestion.
 *
 * Story: Orion Traders (O-1101) network. "Vikram Rao" (N-4821) is the
 * communication/transfer hub; Rahul Mehta and Sana Iqbal connect through him.
 */

import type { SourceType } from "../services/intake";

// Hub phone = Vikram Rao. Spokes = Rahul (N-9044), Sana (N-7712), Anand (N-2210),
// Deepa (N-3377). Hub receives and forwards traffic — strong centrality contrast.
export const CDR = [
  [ "N-4821", "N-9044", "2026-08-14T09:12", "34" ],
  [ "N-9044", "N-4821", "2026-08-14T09:18", "12" ],
  [ "N-4821", "N-7712", "2026-08-14T10:45", "51" ],
  [ "N-7712", "N-4821", "2026-08-14T11:02", "9" ],
  [ "N-4821", "N-2210", "2026-08-14T13:20", "22" ],
  [ "N-2210", "N-4821", "2026-08-14T13:24", "6" ],
  [ "N-4821", "N-3377", "2026-08-14T15:33", "47" ],
  [ "N-3377", "N-4821", "2026-08-14T15:41", "15" ],
  [ "N-9044", "N-7712", "2026-08-14T16:05", "28" ],
  [ "N-7712", "N-9044", "2026-08-14T16:11", "7" ],
  [ "N-4821", "N-9044", "2026-08-15T08:02", "33" ],
  [ "N-4821", "N-2210", "2026-08-15T08:15", "19" ],
  [ "N-4821", "N-3377", "2026-08-15T09:50", "42" ],
  [ "N-3377", "N-4821", "2026-08-15T09:56", "11" ],
  [ "N-9044", "N-4821", "2026-08-15T12:30", "26" ],
  [ "N-7712", "N-4821", "2026-08-15T14:10", "18" ],
  [ "N-4821", "N-7712", "2026-08-15T14:16", "5" ],
  [ "N-2210", "N-3377", "2026-08-15T18:00", "10" ],
];

export const TRANSACTIONS = [
  [ "A-0421", "A-0182", "2400000", "2026-08-14T09:30" ],
  [ "A-0182", "A-0421", "650000", "2026-08-14T10:05" ],
  [ "A-0421", "A-9055", "1800000", "2026-08-14T13:40" ],
  [ "A-9055", "A-0421", "420000", "2026-08-14T14:15" ],
  [ "A-0421", "A-1144", "3100000", "2026-08-15T09:00" ],
  [ "A-1144", "A-0421", "580000", "2026-08-15T09:20" ],
  [ "A-0421", "A-0182", "2750000", "2026-08-15T12:45" ],
];

export const VEHICLES = [
  [ "V-2048", "VIKRAM RAO" ],
  [ "V-3310", "RAHUL MEHTA" ],
  [ "V-8871", "SANA IQBAL" ],
  [ "V-1142", "ANAND PATEL" ],
];

export const LOCATIONS = [
  [ "N-4821", "Kandivali West", "19.075", "72.850", "2026-08-14T09:00" ],
  [ "N-9044", "Goregaon East", "19.165", "72.859", "2026-08-14T09:25" ],
  [ "N-4821", "Malad Industrial", "19.186", "72.849", "2026-08-14T12:00" ],
  [ "N-7712", "Andheri Marol", "19.120", "72.866", "2026-08-14T12:30" ],
  [ "N-2210", "BKC", "19.066", "72.866", "2026-08-14T13:45" ],
  [ "N-4821", "Kandivali West", "19.075", "72.850", "2026-08-15T08:30" ],
  [ "N-3377", "Dadar", "19.018", "72.845", "2026-08-15T09:05" ],
];

export const FIR_TEXT = [
  "Complainant reported an organized smuggling racket operating under the Orion Traders banner (O-1101).",
  "Two suspects known locally as VIKRAM RAO and RAHUL MEHTA were named.",
  "Vehicles V-2048 and V-3310 were observed near the Malad Industrial warehouse on 14 AUG 2026.",
  "The investigation found transfers between bank accounts A-0421 and A-0182 totaling several lakh over consecutive days.",
].join("\n");

export const SURVEILLANCE = [
  { id: "SURV-01", timestamp: "2026-08-14T11:50", text: "Suspect observed entering warehouse; phone in 4821 series detected nearby." },
  { id: "SURV-02", timestamp: "2026-08-14T14:20", text: "Vehicle V-2048 departed Malad Industrial towards Kandivali West." },
  { id: "SURV-03", timestamp: "2026-08-15T10:15", text: "Handover between two unknown persons; exchanged container seals." },
];

function toCSV(headers: string[], rows: string[][]): string {
  return [headers.join(","), ...rows.map((r) => r.join(","))].join("\n") + "\n";
}

export interface DemoFile {
  name: string;
  sourceType: SourceType;
  mime: string;
  content: string;
}

export const DEMO_FILES: DemoFile[] = [
  {
    name: "cdr_august.csv",
    sourceType: "CDR",
    mime: "text/csv",
    content: toCSV(["caller", "receiver", "time", "duration"], CDR),
  },
  {
    name: "transactions_august.csv",
    sourceType: "TRANSACTION",
    mime: "text/csv",
    content: toCSV(["sender", "receiver", "amount", "time"], TRANSACTIONS),
  },
  {
    name: "vehicles.csv",
    sourceType: "VEHICLE",
    mime: "text/csv",
    content: toCSV(["registration_no", "owner_name"], VEHICLES),
  },
  {
    name: "locations_august.csv",
    sourceType: "LOCATION",
    mime: "text/csv",
    content: toCSV(["entity", "area", "lat", "lon", "time"], LOCATIONS),
  },
  {
    name: "fir_001.txt",
    sourceType: "FIR",
    mime: "text/plain",
    content: FIR_TEXT,
  },
  {
    name: "surveillance_august.json",
    sourceType: "SURVEILLANCE",
    mime: "application/json",
    content: JSON.stringify(SURVEILLANCE, null, 2),
  },
];