-- Acknowledgements are evidence for project funding, not a separate graph edge.
SET ROLE smartlib_owner;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM smartlib.relation_assertion
               WHERE predicate='publication.acknowledges_funder'
               AND system_to='infinity'::timestamptz
               AND review_state NOT IN ('superseded','rejected')) THEN
        RAISE EXCEPTION 'Resolve acknowledgement evidence to specific projects before retiring this predicate';
    END IF;
END;
$$;
UPDATE smartlib.relation_predicate_definition
SET lifecycle_state='retired',replacement_predicate='publication.supported_by_project',
    description='已取消独立致谢关系。致谢仅作为项目资助关系的来源证据；未定位项目时保留待匹配线索。',
    updated_at=clock_timestamp()
WHERE predicate='publication.acknowledges_funder';
RESET ROLE;
