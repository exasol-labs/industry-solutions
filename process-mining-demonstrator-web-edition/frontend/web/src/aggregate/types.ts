// Types for the aggregate designer (collapse connected steps into a Σ super-step).

/** One output project's destination: a name + where its data is written. */
export interface AggregateOutput {
  name: string
  /** Empty = the source connection. */
  targetConnectionId: string
  /** Empty = that connection's own schema. A new name creates the schema. */
  targetSchema: string
}

export interface CreateAggregateBody {
  connectionId: string // source connection
  members: string[]
  sigmaName: string
  highLevel: AggregateOutput
  detail: AggregateOutput
}

export interface CreateAggregateResult {
  highLevelProjectId: number
  highLevelConnectionId: string
  detailProjectId: number
  detailConnectionId: string
  sigmaStep: string
}

/** One aggregate group inside a multi-aggregate set: the member steps, a Σ name, and its
 *  own detail-project destination. */
export interface AggregateGroupInput {
  sigmaName: string
  members: string[]
  detail: AggregateOutput
}

/** Create a whole high-level map at once (several Σ groups). */
export interface CreateAggregateSetBody {
  connectionId: string // source connection
  highLevel: AggregateOutput
  aggregates: AggregateGroupInput[]
}

/** Append aggregates to an existing high-level map. */
export interface AddAggregatesBody {
  connectionId: string // the high-level map's connection
  aggregates: AggregateGroupInput[]
}

export interface AggregateSetResult {
  highLevelProjectId: number
  highLevelConnectionId: string
  aggregates: {
    sigmaStep: string
    detailConnectionId: string
    detailProjectId: number
  }[]
}

/** A stored Σ → detail-project link, listed for a high-level project so the app can
 *  offer drill-down on the Σ node. */
export interface AggregateLink {
  connectionId: string
  projectId: number
  sigmaStep: string
  detailConnectionId: string
  detailProjectId: number
}
