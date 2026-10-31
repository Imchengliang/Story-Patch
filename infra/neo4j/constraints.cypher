CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT event_id IF NOT EXISTS FOR (n:Event) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT state_id IF NOT EXISTS FOR (n:State) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT proposition_id IF NOT EXISTS FOR (n:Proposition) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (n:Fact) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT knowledge_state_id IF NOT EXISTS FOR (n:KnowledgeState) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT constraint_id IF NOT EXISTS FOR (n:Constraint) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT gap_id IF NOT EXISTS FOR (n:Gap) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT span_ref_id IF NOT EXISTS FOR (n:SpanRef) REQUIRE n.id IS UNIQUE;

CREATE INDEX entity_canonical_name IF NOT EXISTS FOR (n:Entity) ON (n.canonical_name);
CREATE INDEX event_time IF NOT EXISTS FOR (n:Event) ON (n.valid_from, n.valid_to);
CREATE INDEX fact_validity IF NOT EXISTS FOR (n:Fact) ON (n.valid_from, n.valid_to);
CREATE INDEX fact_provenance IF NOT EXISTS FOR (n:Fact) ON (n.provenance_type);
CREATE INDEX fact_lookup IF NOT EXISTS FOR (n:Fact) ON (n.subject_id, n.predicate, n.object_id);
CREATE INDEX state_validity IF NOT EXISTS FOR (n:State) ON (n.valid_from, n.valid_to);
CREATE INDEX knowledge_validity IF NOT EXISTS FOR (n:KnowledgeState) ON (n.valid_from, n.valid_to);
CREATE INDEX constraint_scope IF NOT EXISTS FOR (n:Constraint) ON (n.scope);
