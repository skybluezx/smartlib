SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

CREATE TABLE smartlib.publication_metric_definition (
 metric_code text PRIMARY KEY CHECK(metric_code ~ '^[a-z][a-z0-9_.]+$'),
 label text NOT NULL, source_field text NOT NULL,
 semantic_level text NOT NULL CHECK(semantic_level IN ('publication','journal_context','normalization_baseline')),
 unit text NOT NULL, aggregation_rule text NOT NULL CHECK(aggregation_rule IN ('sum_and_mean','mean','none')),
 definition text NOT NULL, definition_version text NOT NULL,
 documentation_url text NOT NULL, maximum_value numeric,
 integer_only boolean NOT NULL DEFAULT false
);
INSERT INTO smartlib.publication_metric_definition VALUES
 ('incites.times_cited','被引频次','被引频次','publication','count','sum_and_mean','来源快照中的累计被引次数；不是当年新增引用。','incites-export-v1','https://incites.zendesk.com',NULL,true),
 ('incites.journal_expected_citations','期刊预期被引频次','期刊预期被引频次','normalization_baseline','citations_per_document','none','来源提供的期刊规范化基准，保留原值，不作为论文表现累加。','incites-export-v1','https://incites.zendesk.com',NULL,false),
 ('incites.category_expected_citations','类别预期被引频次','类别预期被引频次','normalization_baseline','citations_per_document','none','来源提供的类别规范化基准；多学科处理取决于来源上下文，不据此重算CNCI。','incites-export-v1','https://incites.zendesk.com',NULL,false),
 ('incites.collaboration_expected_citations','合作学科预期被引频次','合作学科预期被引频次','normalization_baseline','citations_per_document','none','来源提供的合作规范化基准，不是合作论文数量。','incites-export-v1','https://incites.zendesk.com/hc/en-gb/articles/32405722942481-Collaboration-Analysis',NULL,false),
 ('incites.jnci','期刊规范化的引文影响力','期刊规范化的引文影响力','publication','ratio','mean','直接保存来源JNCI；按期刊、出版年和文献类型规范化，不是JIF。','incites-export-v1','https://incites.zendesk.com',NULL,false),
 ('incites.cnci','学科规范化的引文影响力','学科规范化的引文影响力','publication','ratio','mean','直接保存来源CNCI；论文集合先去重，再取逐篇值的算术平均，不以总引用除以总基准替代。','incites-export-v1','https://incites.zendesk.com/hc/en-gb/articles/25087312115601-Category-Normalized-Citation-Impact-CNCI',NULL,false),
 ('incites.collab_cnci','合作规范化的引文影响力','按主题、年份、文献类型和合作类型调整后的规范化引文影响力。','publication','ratio','mean','直接保存来源Collab-CNCI，包含学科、年份、文献类型、合作类型上下文。','incites-export-v1','https://incites.zendesk.com/hc/en-gb/articles/32405722942481-Collaboration-Analysis',NULL,false),
 ('incites.subject_percentile','学科领域百分位','学科领域百分位','publication','percentile_0_100','mean','当前InCites口径数值越大相对引用位置越高；0有效；不自动等同ESI高被引或热门论文。','incites-export-v1','https://incites.zendesk.com/hc/en-gb/articles/25087394395153-Average-Percentile',100,false),
 ('incites.jif_context','期刊影响因子（来源上下文）','期刊影响因子','journal_context','ratio','none','论文关联期刊的JIF；保留导出上下文，不作为论文质量得分，不替代已核验JCR年度发布。','incites-export-v1','https://incites.zendesk.com/hc/en-gb/articles/25088350365457-Journal-Citation-Reports-Data',NULL,false);

CREATE TABLE smartlib.publication_metric_release (
 release_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 source_system_id uuid NOT NULL REFERENCES smartlib.source_system,
 ingestion_batch_id uuid NOT NULL REFERENCES smartlib.ingestion_batch(batch_id),
 provider text NOT NULL, scope_key text NOT NULL,
 dataset_label text NOT NULL, exported_on date NOT NULL,
 dataset_updated_on date NOT NULL, indexed_through date NOT NULL,
 source_uri text NOT NULL, source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[a-f0-9]{64}$'),
 rule_version text NOT NULL,
 expected_publication_count integer NOT NULL CHECK(expected_publication_count>0),
 expected_metric_codes text[] NOT NULL CHECK(cardinality(expected_metric_codes)>0),
 context jsonb NOT NULL CHECK(jsonb_typeof(context)='object'),
 release_state text NOT NULL DEFAULT 'staged' CHECK(release_state IN ('staged','validated','retired')),
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 validated_at timestamptz,
 CHECK(indexed_through<=dataset_updated_on AND dataset_updated_on<=exported_on),
 CHECK(release_state<>'validated' OR validated_at IS NOT NULL),
 UNIQUE(source_sha256,rule_version)
);
CREATE TABLE smartlib.publication_metric_snapshot (
 snapshot_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 release_id uuid NOT NULL REFERENCES smartlib.publication_metric_release,
 publication_id uuid NOT NULL REFERENCES smartlib.publication_metadata,
 source_reference_id uuid NOT NULL REFERENCES smartlib.source_reference,
 ingestion_record_id uuid NOT NULL REFERENCES smartlib.ingestion_record(record_id),
 source_row integer NOT NULL CHECK(source_row>1),
 source_publication_year integer NOT NULL CHECK(source_publication_year BETWEEN 1500 AND 2200),
 local_publication_year_at_import integer,
 source_document_type text, source_research_areas text, source_collaboration_type text,
 raw_fields jsonb NOT NULL CHECK(jsonb_typeof(raw_fields)='object'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(release_id,publication_id), UNIQUE(release_id,source_row)
);
CREATE TABLE smartlib.publication_metric_value (
 snapshot_id uuid NOT NULL REFERENCES smartlib.publication_metric_snapshot,
 metric_code text NOT NULL REFERENCES smartlib.publication_metric_definition,
 numeric_value numeric,
 value_status text NOT NULL CHECK(value_status IN ('present','source_blank','not_supplied')),
 raw_value jsonb,
 PRIMARY KEY(snapshot_id,metric_code),
 CHECK((value_status='present' AND numeric_value IS NOT NULL) OR (value_status<>'present' AND numeric_value IS NULL)),
 CHECK(numeric_value IS NULL OR (numeric_value>=0 AND numeric_value NOT IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)))
);
CREATE INDEX publication_metric_snapshot_publication_idx ON smartlib.publication_metric_snapshot(publication_id,release_id);
CREATE INDEX publication_metric_value_analysis_idx ON smartlib.publication_metric_value(metric_code,numeric_value) WHERE value_status='present';
CREATE INDEX publication_metric_release_latest_idx ON smartlib.publication_metric_release(provider,scope_key,indexed_through DESC,exported_on DESC) WHERE release_state='validated';

CREATE FUNCTION smartlib.guard_publication_metric_record() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE rid uuid; old_rid uuid; def smartlib.publication_metric_definition; snap smartlib.publication_metric_snapshot;
BEGIN
 IF TG_TABLE_NAME='publication_metric_snapshot' THEN
   rid=COALESCE(NEW.release_id,OLD.release_id); old_rid=OLD.release_id;
   IF TG_OP<>'DELETE' AND NOT EXISTS(SELECT 1 FROM smartlib.source_reference sr JOIN smartlib.ingestion_record ir ON ir.record_id=NEW.ingestion_record_id JOIN smartlib.publication_metric_release r ON r.release_id=NEW.release_id WHERE sr.source_reference_id=NEW.source_reference_id AND sr.object_id=NEW.publication_id AND sr.source_system_id=r.source_system_id AND ir.batch_id=r.ingestion_batch_id) THEN RAISE EXCEPTION 'metric source identity mismatch'; END IF;
 ELSE
   SELECT * INTO snap FROM smartlib.publication_metric_snapshot WHERE snapshot_id=COALESCE(NEW.snapshot_id,OLD.snapshot_id); rid=snap.release_id;
   IF TG_OP<>'INSERT' THEN SELECT release_id INTO old_rid FROM smartlib.publication_metric_snapshot WHERE snapshot_id=OLD.snapshot_id; END IF;
   IF TG_OP<>'DELETE' THEN
     SELECT * INTO STRICT def FROM smartlib.publication_metric_definition WHERE metric_code=NEW.metric_code;
     IF NOT EXISTS(SELECT 1 FROM smartlib.publication_metric_release WHERE release_id=rid AND NEW.metric_code=ANY(expected_metric_codes)) THEN RAISE EXCEPTION 'unexpected metric code'; END IF;
     IF NEW.numeric_value>def.maximum_value OR (def.integer_only AND NEW.numeric_value<>trunc(NEW.numeric_value)) THEN RAISE EXCEPTION 'metric value outside definition'; END IF;
     IF NEW.raw_value IS DISTINCT FROM snap.raw_fields->def.source_field THEN RAISE EXCEPTION 'metric raw value mismatch'; END IF;
     IF NEW.value_status='present' AND NEW.numeric_value IS DISTINCT FROM (snap.raw_fields->>def.source_field)::numeric THEN RAISE EXCEPTION 'metric numeric value mismatch'; END IF;
     IF NEW.value_status='source_blank' AND (NOT snap.raw_fields ? def.source_field OR NULLIF(btrim(snap.raw_fields->>def.source_field),'') IS NOT NULL) THEN RAISE EXCEPTION 'invalid source blank'; END IF;
     IF NEW.value_status='not_supplied' AND snap.raw_fields ? def.source_field THEN RAISE EXCEPTION 'field supplied'; END IF;
   END IF;
 END IF;
 -- Lock the release to serialize publication with concurrent record writes.
 PERFORM 1 FROM smartlib.publication_metric_release WHERE release_id IN (rid,old_rid) FOR UPDATE;
 IF EXISTS(SELECT 1 FROM smartlib.publication_metric_release WHERE release_id IN (rid,old_rid) AND release_state<>'staged') THEN RAISE EXCEPTION 'validated metric snapshots are immutable'; END IF;
 RETURN COALESCE(NEW,OLD);
END $$;
CREATE TRIGGER metric_snapshot_guard BEFORE INSERT OR UPDATE OR DELETE ON smartlib.publication_metric_snapshot FOR EACH ROW EXECUTE FUNCTION smartlib.guard_publication_metric_record();
CREATE TRIGGER metric_value_guard BEFORE INSERT OR UPDATE OR DELETE ON smartlib.publication_metric_value FOR EACH ROW EXECUTE FUNCTION smartlib.guard_publication_metric_record();

CREATE FUNCTION smartlib.guard_publication_metric_release() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' AND NEW.release_state<>'staged' THEN RAISE EXCEPTION 'metric release must start staged'; END IF;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'retire metric release instead of deleting'; END IF;
 IF TG_OP='UPDATE' AND OLD.release_state<>'staged' THEN
   IF NOT(OLD.release_state='validated' AND NEW.release_state='retired' AND to_jsonb(NEW)-'release_state'=to_jsonb(OLD)-'release_state') THEN RAISE EXCEPTION 'validated metric release is immutable'; END IF;
 END IF;
 IF NEW.release_state='validated' THEN
   IF (SELECT count(*) FROM smartlib.publication_metric_snapshot WHERE release_id=NEW.release_id)<>NEW.expected_publication_count THEN RAISE EXCEPTION 'metric publication coverage mismatch'; END IF;
   IF EXISTS(SELECT 1 FROM smartlib.publication_metric_snapshot s WHERE s.release_id=NEW.release_id AND (SELECT array_agg(v.metric_code ORDER BY v.metric_code) FROM smartlib.publication_metric_value v WHERE v.snapshot_id=s.snapshot_id) IS DISTINCT FROM (SELECT array_agg(x ORDER BY x) FROM unnest(NEW.expected_metric_codes) x)) THEN RAISE EXCEPTION 'metric matrix incomplete'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER metric_release_guard BEFORE INSERT OR UPDATE OR DELETE ON smartlib.publication_metric_release FOR EACH ROW EXECUTE FUNCTION smartlib.guard_publication_metric_release();
CREATE TRIGGER metric_release_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.publication_metric_release FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('release_id');

INSERT INTO smartlib.access_permission(code,name,risk_level) VALUES
 ('publication_metric.read','查看论文来源指标','read'),('publication_metric.import','导入论文指标版本','high');
INSERT INTO smartlib.access_role_permission(role_id,permission_id)
 SELECT r.role_id,p.permission_id FROM smartlib.access_role r CROSS JOIN smartlib.access_permission p
 WHERE p.code LIKE 'publication_metric.%' AND (r.code='knowledge_admin' OR (r.code IN ('publication_reviewer','system_observer') AND p.code='publication_metric.read'));
GRANT SELECT ON smartlib.publication_metric_definition TO smartlib_app,smartlib_readonly;
GRANT SELECT,INSERT,UPDATE ON smartlib.publication_metric_release TO smartlib_app;
GRANT SELECT,INSERT ON smartlib.publication_metric_snapshot,smartlib.publication_metric_value TO smartlib_app;
GRANT SELECT ON smartlib.publication_metric_release,smartlib.publication_metric_snapshot,smartlib.publication_metric_value TO smartlib_readonly;
ALTER TABLE smartlib.publication_metric_release ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_metric_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlib.publication_metric_value ENABLE ROW LEVEL SECURITY;
CREATE POLICY metric_release_read ON smartlib.publication_metric_release FOR SELECT TO smartlib_app,smartlib_readonly USING(smartlib.actor_has_permission(smartlib.current_actor_id(),'publication_metric.read') AND EXISTS(SELECT 1 FROM smartlib.source_system s WHERE s.source_system_id=publication_metric_release.source_system_id AND s.authorization_state='approved'));
CREATE POLICY metric_release_write ON smartlib.publication_metric_release FOR ALL TO smartlib_app USING(smartlib.actor_has_permission(smartlib.current_actor_id(),'publication_metric.import')) WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'publication_metric.import') AND created_by=smartlib.current_actor_id());
CREATE POLICY metric_snapshot_read ON smartlib.publication_metric_snapshot FOR SELECT TO smartlib_app,smartlib_readonly USING(EXISTS(SELECT 1 FROM smartlib.publication_metric_release r WHERE r.release_id=publication_metric_snapshot.release_id) AND EXISTS(SELECT 1 FROM smartlib.knowledge_object k WHERE k.object_id=publication_metric_snapshot.publication_id));
CREATE POLICY metric_snapshot_write ON smartlib.publication_metric_snapshot FOR INSERT TO smartlib_app WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'publication_metric.import'));
CREATE POLICY metric_value_read ON smartlib.publication_metric_value FOR SELECT TO smartlib_app,smartlib_readonly USING(EXISTS(SELECT 1 FROM smartlib.publication_metric_snapshot s WHERE s.snapshot_id=publication_metric_value.snapshot_id));
CREATE POLICY metric_value_write ON smartlib.publication_metric_value FOR INSERT TO smartlib_app WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'publication_metric.import'));

CREATE VIEW smartlib.publication_metric_latest_release WITH(security_invoker=true) AS
 SELECT DISTINCT ON(provider,scope_key) * FROM smartlib.publication_metric_release WHERE release_state='validated'
 ORDER BY provider,scope_key,indexed_through DESC,dataset_updated_on DESC,exported_on DESC,created_at DESC;
CREATE VIEW smartlib.publication_metric_analysis WITH(security_invoker=true) AS
 SELECT s.release_id,s.publication_id,s.source_publication_year,s.source_document_type,s.source_research_areas,s.source_collaboration_type,
 v.metric_code,v.numeric_value,v.value_status,d.semantic_level,d.unit,d.aggregation_rule,s.source_reference_id
 FROM smartlib.publication_metric_snapshot s JOIN smartlib.publication_metric_value v USING(snapshot_id)
 JOIN smartlib.publication_metric_definition d USING(metric_code) JOIN smartlib.publication_metric_release r USING(release_id)
 WHERE r.release_state='validated';
GRANT SELECT ON smartlib.publication_metric_latest_release,smartlib.publication_metric_analysis TO smartlib_app,smartlib_readonly;
RESET ROLE;
