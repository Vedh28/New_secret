import { Entity } from "../types";

export const dashboardMetrics = [
  { label: "Active Investigations", value: 128 },
  { label: "Entities Monitored", value: 24891 },
  { label: "Relationships Mapped", value: 182430 },
  { label: "High-Risk Alerts", value: 17 }
];

export const entities: Entity[] = [
  { id: "P-8801", name: "R. Sharma", type: "Person", risk: 96, confidence: 94, relationships: 24, lastActivity: "15:10", aliases: ["R.S.", "Apex Leader"], phones: ["+91-XXX-1011"], vehicles: ["DL-3301"], locations: ["New Delhi Central Hub", "Noida Cyber Zone"], organizations: ["Apex Cyber"], },
  { id: "P-2041", name: "A. Khan", type: "Person", risk: 94, confidence: 96, relationships: 18, lastActivity: "14:32", aliases: ["A. Khan", "Alpha"], phones: ["+91-XXX-4821"], vehicles: ["MH-2048"], locations: ["Mumbai CSMT", "Kandivali West"], organizations: ["Orion"], },
  { id: "P-4402", name: "V. Nair", type: "Person", risk: 91, confidence: 92, relationships: 16, lastActivity: "14:15", aliases: ["Trident Lead"], phones: ["+91-XXX-7704"], vehicles: ["KA-7711"], locations: ["Bengaluru Tech Corridor", "Hyderabad HITEC City"], organizations: ["Deccan Marine"], },
  { id: "P-3310", name: "D. Patel", type: "Person", risk: 89, confidence: 91, relationships: 14, lastActivity: "13:20", aliases: ["Falcon Ring"], phones: ["+91-XXX-3341"], vehicles: ["GJ-8802"], locations: ["Ahmedabad GIFT City", "Surat Diamond Park"], organizations: ["GIFT City Ring"], },
  { id: "P-6601", name: "S. Banerjee", type: "Person", risk: 87, confidence: 90, relationships: 15, lastActivity: "10:00", aliases: ["Eastern Lead"], phones: ["+91-XXX-8812"], vehicles: ["WB-5502"], locations: ["Kolkata Salt Lake", "Guwahati Outpost"], organizations: ["Eastern Delta"], },
  { id: "O-1101", name: "Organization Orion", type: "Organization", risk: 89, confidence: 92, relationships: 44, lastActivity: "14:27", aliases: ["Orion Group"], locations: ["Mumbai CSMT"], organizations: ["Orion"], },
  { id: "O-9901", name: "Apex Cyber Syndicate", type: "Organization", risk: 92, confidence: 95, relationships: 38, lastActivity: "15:00", aliases: ["Apex Syndicate"], locations: ["Noida Cyber Zone"], organizations: ["Apex Cyber"], },
  { id: "V-2048", name: "Transit Vehicle MH-02", type: "Vehicle", risk: 58, confidence: 84, relationships: 7, lastActivity: "11:46", aliases: ["Black sedan"], locations: ["Kandivali West"], },
  { id: "A-4200", name: "Escrow Ledger 4200", type: "Account", risk: 76, confidence: 87, relationships: 9, lastActivity: "09:17", aliases: ["Ledger 4200"], organizations: ["Orion"], }
];

export const alerts = [
  { severity: "CRITICAL", title: "Rapid expansion of entity network", time: "14:32:08" },
  { severity: "HIGH", title: "Unusual transaction pattern", time: "14:31:44" },
  { severity: "MEDIUM", title: "New communication cluster identified", time: "14:29:17" },
  { severity: "LOW", title: "Entity risk score updated", time: "14:27:03" }
];

export const feed = [
  "New relationship discovered",
  "Suspicious transaction detected",
  "New communication cluster identified",
  "Entity risk score updated"
];
