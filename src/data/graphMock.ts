/**
 * Synthetic offline graph used when the backend is unreachable.
 *
 * Full Pan-India Multi-State National Intelligence Graph.
 */
import type { GraphResponse } from "../services/api";

export const mockGraph: GraphResponse = {
  nodes: [
    // Maharashtra & West
    { id: "P-2041", type: "PERSON", name: "A. Khan (Mumbai/Pune)", properties: { risk: 94, confidence: 96 } },
    { id: "P-7712", type: "PERSON", name: "B. Malik (Nagpur)", properties: { risk: 71, confidence: 88 } },
    { id: "O-1101", type: "ORGANIZATION", name: "Orion Logistics Western", properties: { risk: 89 } },
    { id: "V-2048", type: "VEHICLE", name: "Transit Vehicle MH-02", properties: { risk: 58 } },
    { id: "N-4821", type: "PHONE", name: "Comms Relay 4821 (Mumbai)", properties: { risk: 62 } },
    { id: "A-4200", type: "ACCOUNT", name: "Escrow Ledger 4200", properties: { risk: 76 } },

    // Northern Grid (Delhi NCR, Kashmir, Punjab, UP)
    { id: "P-8801", type: "PERSON", name: "R. Sharma (Delhi NCR)", properties: { risk: 96, confidence: 94 } },
    { id: "O-9901", type: "ORGANIZATION", name: "Apex Cyber Syndicate (Noida)", properties: { risk: 92 } },
    { id: "N-1011", type: "PHONE", name: "Encrypted Sat-Phone 1011 (Delhi)", properties: { risk: 88 } },
    { id: "N-5520", type: "PHONE", name: "VHF Link 5520 (Srinagar)", properties: { risk: 79 } },
    { id: "V-3301", type: "VEHICLE", name: "Armored Van DL-01", properties: { risk: 65 } },
    { id: "A-8801", type: "ACCOUNT", name: "Digital Wallet A-8801", properties: { risk: 84 } },

    // Southern Axis (Bengaluru, Hyderabad, Chennai, Kochi)
    { id: "P-4402", type: "PERSON", name: "V. Nair (Bengaluru)", properties: { risk: 91, confidence: 92 } },
    { id: "O-3302", type: "ORGANIZATION", name: "Deccan Marine Shipping (Chennai)", properties: { risk: 85 } },
    { id: "N-7704", type: "PHONE", name: "VoIP Trunk 7704 (Hyderabad)", properties: { risk: 74 } },
    { id: "V-7711", type: "VEHICLE", name: "Cargo Freight KA-04", properties: { risk: 60 } },
    { id: "A-9904", type: "ACCOUNT", name: "Maritime Clearing 9904", properties: { risk: 81 } },

    // Eastern Gateway (Kolkata, Howrah, Patna, Guwahati)
    { id: "P-6601", type: "PERSON", name: "S. Banerjee (Kolkata)", properties: { risk: 87, confidence: 90 } },
    { id: "O-5501", type: "ORGANIZATION", name: "Eastern Delta Freight (Howrah)", properties: { risk: 83 } },
    { id: "N-8812", type: "PHONE", name: "Cell Node 8812 (Patna)", properties: { risk: 68 } },
    { id: "N-9911", type: "PHONE", name: "Repeater Node 9911 (Guwahati)", properties: { risk: 75 } },
    { id: "V-5502", type: "VEHICLE", name: "Rail Consignment WB-08", properties: { risk: 55 } },
    { id: "A-5501", type: "ACCOUNT", name: "Coastal Clearing A-5501", properties: { risk: 72 } },

    // Western & Central (Ahmedabad, Jaipur, Bhopal, Raipur)
    { id: "P-3310", type: "PERSON", name: "D. Patel (Ahmedabad)", properties: { risk: 89, confidence: 91 } },
    { id: "O-2201", type: "ORGANIZATION", name: "GIFT City Trading Ring", properties: { risk: 86 } },
    { id: "N-3341", type: "PHONE", name: "Telecom Uplink 3341 (Jaipur)", properties: { risk: 70 } },
    { id: "V-8802", type: "VEHICLE", name: "Highway Transport GJ-01", properties: { risk: 52 } },
    { id: "A-7700", type: "ACCOUNT", name: "Bullion Ledger 7700", properties: { risk: 88 } },
  ],
  edges: [
    // Cross-regional national ties
    { id: "E-001", source: "P-2041", target: "O-1101", type: "MEMBER_OF", properties: { confidence: 0.92 } },
    { id: "E-002", source: "P-2041", target: "P-8801", type: "ASSOCIATED_WITH", properties: { confidence: 0.88 } },
    { id: "E-003", source: "P-8801", target: "O-9901", type: "MEMBER_OF", properties: { confidence: 0.95 } },
    { id: "E-004", source: "P-8801", target: "N-1011", type: "USES", properties: { confidence: 0.94 } },
    { id: "E-005", source: "P-8801", target: "P-4402", type: "COMMUNICATED_WITH", properties: { confidence: 0.91 } },
    { id: "E-006", source: "P-4402", target: "O-3302", type: "CONTROLS", properties: { confidence: 0.89 } },
    { id: "E-007", source: "P-4402", target: "P-6601", type: "ASSOCIATED_WITH", properties: { confidence: 0.85 } },
    { id: "E-008", source: "P-6601", target: "O-5501", type: "MEMBER_OF", properties: { confidence: 0.9 } },
    { id: "E-009", source: "P-6601", target: "P-3310", type: "COMMUNICATED_WITH", properties: { confidence: 0.83 } },
    { id: "E-010", source: "P-3310", target: "O-2201", type: "MEMBER_OF", properties: { confidence: 0.93 } },
    { id: "E-011", source: "P-3310", target: "P-2041", type: "TRANSFERRED_TO", properties: { confidence: 0.96, amount: 4800000 } },
    { id: "E-012", source: "A-4200", target: "A-8801", type: "TRANSFERRED_TO", properties: { confidence: 0.97, amount: 8200000 } },
    { id: "E-013", source: "A-8801", target: "A-9904", type: "TRANSFERRED_TO", properties: { confidence: 0.95, amount: 5600000 } },
    { id: "E-014", source: "A-9904", target: "A-7700", type: "TRANSFERRED_TO", properties: { confidence: 0.94, amount: 9100000 } },
    { id: "E-015", source: "P-8801", target: "N-5520", type: "USES", properties: { confidence: 0.87 } },
    { id: "E-016", source: "P-6601", target: "N-9911", type: "USES", properties: { confidence: 0.82 } },
  ],
};

export const mockInfluencers = [
  { id: "P-8801", name: "R. Sharma (Delhi NCR)", score: 98.4 },
  { id: "P-2041", name: "A. Khan (Mumbai/Pune)", score: 94.8 },
  { id: "P-4402", name: "V. Nair (Bengaluru)", score: 91.2 },
  { id: "P-3310", name: "D. Patel (Ahmedabad)", score: 89.6 },
  { id: "P-6601", name: "S. Banerjee (Kolkata)", score: 87.5 },
];
