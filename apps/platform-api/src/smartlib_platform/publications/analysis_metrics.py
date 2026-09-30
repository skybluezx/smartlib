"""Publication-year journal evidence shared by analytics and catalog details."""
from uuid import UUID

from smartlib_platform.foundation.database import DbConnection


def load_journal_metric_rows(connection: DbConnection, publication_ids: list[UUID]) -> list[dict]:
    if not publication_ids:
        return []
    return connection.execute(
        """SELECT match.publication_id,release.metric_system,release.metric_year,release.release_id,
                  release.release_label,record.impact_factor,record.quartile,record.record_id,
                  record.impact_factor_is_upper_bound,record.source_row_number,
                  ARRAY(SELECT category.category_name
                          FROM smartlib.journal_metric_record_category category
                         WHERE category.record_id=record.record_id
                         ORDER BY category.category_order) AS categories
             FROM smartlib.publication_journal_metric_match match
             JOIN smartlib.journal_metric_record record ON record.record_id=match.record_id
             JOIN smartlib.journal_metric_release release ON release.release_id=record.release_id
             JOIN smartlib.publication_metadata metadata
               ON metadata.publication_id=match.publication_id
            WHERE match.match_state='matched'
              AND match.year_policy='publication_year'
              AND smartlib.journal_metric_analysis_eligible(release.release_id)
              AND release.metric_year=metadata.publication_year
              AND match.publication_id=ANY(%s::uuid[])
            ORDER BY match.publication_id,release.metric_system,record.record_id""",
        (publication_ids,),
    ).fetchall()
