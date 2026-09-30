SET ROLE smartlib_owner;

CREATE FUNCTION audit.reject_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'audit events are append-only' USING ERRCODE = '55000';
END
$function$;

CREATE TRIGGER audit_event_reject_update
BEFORE UPDATE ON audit.audit_event
FOR EACH ROW EXECUTE FUNCTION audit.reject_audit_mutation();

CREATE TRIGGER audit_event_reject_delete
BEFORE DELETE ON audit.audit_event
FOR EACH ROW EXECUTE FUNCTION audit.reject_audit_mutation();

REVOKE ALL ON FUNCTION audit.reject_audit_mutation() FROM PUBLIC;

RESET ROLE;
