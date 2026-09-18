export type Section =
  | "login"
  | "command-center"
  | "investigations"
  | "case-intake"
  | "network"
  | "entities"
  | "timeline"
  | "locations"
  | "transactions"
  | "communications"
  | "alerts"
  | "reports"
  | "settings"
  | "assistant"
  | "simulation"
  | "audit"
  | "integrity";

export type EntityType = "Person" | "Organization" | "Vehicle" | "Phone" | "Location" | "Account";

export type Entity = {
  id: string;
  name: string;
  type: EntityType;
  risk: number;
  confidence: number;
  relationships: number;
  lastActivity: string;
  aliases: string[];
  phones?: string[];
  vehicles?: string[];
  locations?: string[];
  organizations?: string[];
};

/**
 * Unified geographic data contract for the Investigation Map. Both the live
 * backend and the offline synthetic dataset resolve to these shapes so the map
 * renders exactly one source of truth regardless of connectivity.
 */

export type LocationType =
  | "safehouse"
  | "warehouse"
  | "contact"
  | "transfer"
  | "transit"
  | "unknown";

export type CaseLocation = {
  id: string;
  caseId: string;
  name: string;
  latitude: number;
  longitude: number;
  type: LocationType;
  importance: number;
  timestamp: string;
  entityIds: string[];
  entityNames?: string[];
  eventIds: string[];
  observationCount?: number;
  sourceCount?: number;
};

export type LocationEvent = {
  id: string;
  caseId: string;
  locationId: string;
  timestamp: string;
  type: string;
  entityIds: string[];
  description: string;
  sourceIds: string[];
};

export type CaseMarker = {
  caseId: string;
  title: string;
  priority: string;
  status: string;
  locationIds: string[];
  entityIds: string[];
  eventIds: string[];
  locations: CaseLocation[];
  events: LocationEvent[];
  lastActivity: string;
};
