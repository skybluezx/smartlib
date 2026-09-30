from uuid import UUID

from smartlib_platform.foundation.database import DbConnection

from .models import JournalMetricReleaseView, PublicationJournalMetricView


def list_journal_metric_releases(connection: DbConnection) -> list[JournalMetricReleaseView]:
    rows = connection.execute(
        """SELECT release.release_id, release.data_asset_version_id,
                  release.metric_system, release.edition_year, release.metric_year,
                  release.release_label, release.publisher_name,
                  release.authority_status, release.release_state,
                  release.expected_record_count,
                  count(record.record_id)::integer AS actual_record_count,
                  EXISTS (
                      SELECT 1 FROM smartlib.license_grant license
                       WHERE license.data_asset_id = asset.data_asset_id
                         AND license.authorization_state = 'approved'
                         AND (license.valid_from IS NULL OR license.valid_from <= clock_timestamp())
                         AND (license.valid_to IS NULL OR license.valid_to > clock_timestamp())
                         AND 'publication_governance' = ANY(license.allowed_purposes)
                  ) AS license_effective,
                  source.authorization_state AS source_authorization_state,
                  release.source_file_checksum, release.created_at, release.verified_at
             FROM smartlib.journal_metric_release release
             JOIN smartlib.data_asset_version version
               ON version.data_asset_version_id = release.data_asset_version_id
             JOIN smartlib.data_asset asset ON asset.data_asset_id = version.data_asset_id
             JOIN smartlib.source_system source ON source.source_system_id = asset.source_system_id
             LEFT JOIN smartlib.journal_metric_record record
               ON record.release_id = release.release_id
            GROUP BY release.release_id, asset.data_asset_id, source.authorization_state
            ORDER BY release.edition_year DESC, release.created_at DESC"""
    ).fetchall()
    return [JournalMetricReleaseView.model_validate(row) for row in rows]


def list_publication_journal_metrics(
    connection: DbConnection, publication_id: UUID
) -> list[PublicationJournalMetricView]:
    rows = connection.execute(
        """SELECT match.match_id, match.publication_id, release.release_id,
                  release.metric_system, release.edition_year, release.metric_year,
                  journal.journal_id, journal.canonical_title AS journal_title,
                  journal.issn, journal.eissn,
                  COALESCE((
                      SELECT array_agg(item.category_name ORDER BY item.category_order)
                        FROM smartlib.journal_metric_record_category item
                       WHERE item.record_id = record.record_id
                  ), ARRAY[]::text[]) AS categories,
                  COALESCE((
                      SELECT array_agg(DISTINCT index_name ORDER BY index_name)
                        FROM smartlib.journal_metric_record_category item
                       CROSS JOIN LATERAL unnest(item.citation_indexes) index_name
                       WHERE item.record_id = record.record_id
                  ), ARRAY[]::text[]) AS citation_indexes,
                  record.impact_factor, record.impact_factor_is_upper_bound,
                  record.quartile, record.rank_position,
                  record.rank_total, record.record_granularity,
                  match.match_basis, match.match_state, match.confidence,
                  match.year_policy, match.decision_reason
             FROM smartlib.publication_journal_metric_match match
             JOIN smartlib.journal_metric_record record ON record.record_id = match.record_id
             JOIN smartlib.journal_metric_release release ON release.release_id = record.release_id
             JOIN smartlib.journal_identity journal ON journal.journal_id = record.journal_id
            WHERE match.publication_id = %s
              AND smartlib.journal_metric_analysis_eligible(release.release_id)
              AND match.match_state = 'matched'
              AND match.year_policy = 'publication_year'
              AND release.metric_year = (
                  SELECT publication_year FROM smartlib.publication_metadata
                   WHERE publication_id = match.publication_id
              )
            ORDER BY release.edition_year DESC, record.source_row_number""",
        (publication_id,),
    ).fetchall()
    return [PublicationJournalMetricView.model_validate(row) for row in rows]
