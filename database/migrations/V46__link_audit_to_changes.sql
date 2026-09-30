SET ROLE smartlib_owner;
ALTER TABLE audit.audit_event ADD COLUMN change_id uuid REFERENCES smartlib.change_event(change_id);
ALTER TABLE audit.audit_event ADD COLUMN submission_id uuid;
CREATE FUNCTION audit.attach_change_context() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib,audit AS $$
BEGIN
 SELECT c.change_id INTO NEW.change_id FROM smartlib.change_event c WHERE transaction_id=txid_current();
 NEW.submission_id:=nullif(current_setting('smartlib.submission_id',true),'')::uuid;
 RETURN NEW;
END $$;
CREATE TRIGGER audit_change_context BEFORE INSERT ON audit.audit_event
 FOR EACH ROW EXECUTE FUNCTION audit.attach_change_context();
REVOKE ALL ON FUNCTION audit.attach_change_context() FROM PUBLIC;
RESET ROLE;
