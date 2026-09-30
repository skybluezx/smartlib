"""Preview or publish JCR for internal analysis without claiming verification."""
import argparse
import json
import os

import psycopg
from psycopg.rows import dict_row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('smartlib.actor_id',%s,true)",
                           (os.environ['SMARTLIB_DEV_ACTOR_ID'],))
        rows = connection.execute("""SELECT release_id,edition_year,metric_year,
          expected_record_count,release_state,authority_status
          FROM smartlib.journal_metric_release WHERE metric_system='jcr'
          AND release_state IN ('staged','validated') AND authority_status<>'rejected'
          ORDER BY metric_year""").fetchall()
        if args.apply:
            for row in rows:
                connection.execute('SELECT smartlib.publish_provisional_jcr_release(%s,%s)',
                                   (row['release_id'], args.reason))
        print(json.dumps({'applied': args.apply, 'releases': rows},default=str,ensure_ascii=False))


if __name__ == '__main__':
    main()
