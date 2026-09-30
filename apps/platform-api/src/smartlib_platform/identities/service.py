"""Person/organization identity details; all edits use the shared review workflow."""

import re
from uuid import uuid4

from psycopg import sql

PERSON_FIELDS = {"given_name", "family_name", "preferred_language"}
ORGANIZATION_FIELDS = {"organization_type", "country_code"}
ORGANIZATION_TYPES = {
    "university",
    "hospital",
    "research_institute",
    "company",
    "government",
    "nonprofit",
    "department",
    "other",
}
IDENTITY_TYPES = {"person", "organization", "department"}


def prefix(object_type):
    if object_type not in IDENTITY_TYPES:
        raise ValueError("This object has no person/organization identity profile")
    return "person" if object_type == "person" else "organization"


def get_identity(c, object_id):
    obj = c.execute(
        """SELECT object_id,object_type,canonical_name,version FROM smartlib.knowledge_object
                          WHERE object_id=%s
                          AND system_to='infinity' """,
        (object_id,),
    ).fetchone()
    if not obj:
        raise LookupError("Identity object not found")
    kind = prefix(obj["object_type"])
    profile = c.execute(
        sql.SQL("SELECT * FROM smartlib.{}_profile WHERE object_id=%s").format(sql.SQL(kind)), (object_id,)
    ).fetchone()
    if profile is None:
        raise LookupError("Identity profile not found")
    identifiers = c.execute(
        sql.SQL(
            """SELECT * FROM smartlib.{}_identifier
                          WHERE object_id=%s
                          AND verification_status='matched'
                          ORDER BY identifier_type"""
        ).format(sql.SQL(kind)),
        (object_id,),
    ).fetchall()
    names = c.execute(
        sql.SQL(
            """SELECT * FROM smartlib.{}_name_variant
                          WHERE object_id=%s
                          AND verification_status='matched'
                          ORDER BY name_kind,normalized_name"""
        ).format(sql.SQL(kind)),
        (object_id,),
    ).fetchall()
    return {**obj, "profile": profile, "identifiers": identifiers, "names": names}


def current_value(identity, path):
    if path.startswith("profile."):
        return identity["profile"].get(path[8:])
    if path == "identity.aliases":
        return sorted(n["name"] for n in identity["names"] if n["name_kind"] == "alias")
    return next(
        (i["normalized_value"] for i in identity["identifiers"] if i["identifier_type"] == path[12:]), None
    )


def normalize(c, object_type, path, value):
    kind = prefix(object_type)
    if path.startswith("profile."):
        field = path[8:]
        allowed = PERSON_FIELDS if kind == "person" else ORGANIZATION_FIELDS
        if field not in allowed:
            raise ValueError("Unsupported identity profile field")
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError("Profile value requires nonempty text up to 200 characters")
        value = value.strip()
        if field == "country_code":
            value = value.upper()
            if not re.fullmatch(r"[A-Z]{2}", value):
                raise ValueError("Country/region code must contain two letters")
        if field == "organization_type" and value not in ORGANIZATION_TYPES:
            raise ValueError("Unsupported organization type")
        if field == "preferred_language" and not re.fullmatch(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})*", value):
            raise ValueError("Invalid language tag")
        return value
    if path == "identity.aliases":
        if not isinstance(value, list) or len(value) > 50:
            raise ValueError("Provide up to 50 alternative names")
        names = {}
        for name in value:
            if not isinstance(name, str) or not name.strip() or len(name) > 500:
                raise ValueError("Each alternative name must be nonempty text up to 500 characters")
            name = " ".join(name.split())
            names[name.casefold()] = name
        return sorted(names.values())
    expected = "orcid" if kind == "person" else "ror"
    if path != "identifiers." + expected:
        raise ValueError("Use ORCID for people and ROR for organizations")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Identifier must be text")
    value = re.sub(r"^https?://(?:www\.)?(?:orcid\.org|ror\.org)/", "", value.strip(), flags=re.I)
    if expected == "orcid":
        value = value.upper()
        if not c.execute("SELECT smartlib.valid_orcid(%s) ok", (value,)).fetchone()["ok"]:
            raise ValueError("Invalid ORCID format or checksum")
    else:
        value = value.lower()
        if not re.fullmatch(r"0[0-9a-hjkmnp-tv-z]{6}[0-9]{2}", value):
            raise ValueError("Invalid ROR identifier format")
    return value


def apply(c, row, updates, submission, actor):
    kind = prefix(row["object_type"])
    oid = row["object_id"]
    eid, sid = submission["evidence_id"], submission["submission_id"]
    for path, raw in updates.items():
        value = normalize(c, row["object_type"], path, raw)
        if path.startswith("profile."):
            c.execute(
                sql.SQL(
                    "UPDATE smartlib.{}_profile SET {}=%s,evidence_id=%s,submission_id=%s WHERE object_id=%s"
                ).format(sql.SQL(kind), sql.Identifier(path[8:])),
                (value, eid, sid, oid),
            )
        elif path == "identity.aliases":
            c.execute(
                sql.SQL(
                    """UPDATE smartlib.{}_name_variant
                          SET verification_status='rejected',evidence_id=%s,submission_id=%s
                          WHERE object_id=%s
                          AND name_kind='alias'
                          AND verification_status='matched'"""
                ).format(sql.SQL(kind)),
                (eid, sid, oid),
            )
            for name in value:
                c.execute(
                    sql.SQL("""INSERT INTO smartlib.{}_name_variant
                          (object_id,name,name_kind,evidence_id,submission_id,created_by)
                          VALUES(%s,%s,'alias',%s,%s,%s)
                          ON CONFLICT(object_id,normalized_name,name_kind) DO UPDATE
                          SET name=excluded.name,
                          verification_status='matched',evidence_id=excluded.evidence_id,submission_id=excluded.submission_id""").format(
                        sql.SQL(kind)
                    ),
                    (oid, name, eid, sid, actor),
                )
        else:
            identifier_type = path[12:]
            c.execute(
                sql.SQL(
                    """UPDATE smartlib.{}_identifier
                          SET verification_status='rejected',evidence_id=%s,submission_id=%s
                          WHERE object_id=%s
                          AND identifier_type=%s
                          AND verification_status='matched'"""
                ).format(sql.SQL(kind)),
                (eid, sid, oid, identifier_type),
            )
            if value is not None:
                c.execute(
                    sql.SQL("""INSERT INTO smartlib.{}_identifier(identifier_id,object_id,identifier_type,
                          normalized_value,evidence_id,submission_id,created_by)
                          VALUES(%s,%s,%s,%s,%s,%s,%s)
                          ON CONFLICT(object_id,identifier_type,normalized_value) DO UPDATE SET
                          verification_status='matched',evidence_id=excluded.evidence_id,submission_id=excluded.submission_id""").format(
                        sql.SQL(kind)
                    ),
                    (uuid4(), oid, identifier_type, value, eid, sid, actor),
                )
