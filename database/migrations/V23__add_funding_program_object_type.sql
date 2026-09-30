SET ROLE smartlib_owner;

ALTER TABLE smartlib.knowledge_object
    DROP CONSTRAINT knowledge_object_object_type_check;

ALTER TABLE smartlib.knowledge_object
    ADD CONSTRAINT knowledge_object_object_type_check CHECK (
        object_type IN (
            'person', 'organization', 'department', 'discipline', 'funding_program',
            'project', 'publication', 'dataset', 'patent', 'resource', 'event',
            'concept', 'requirement'
        )
    );

COMMENT ON CONSTRAINT knowledge_object_object_type_check ON smartlib.knowledge_object IS
    'Funding programmes are modeled separately from the individual grants awarded under them';

RESET ROLE;
