"""SAMPLE DATA ONLY: fills the DEV copy of databases/inboxUsage.db with made-up
logins so the ABOUT > USAGE view can be looked at before anything records real
ones. Nothing here is real usage. Refuses to touch an existing file unless
--force; the databases folder is never committed or deployed.

    python 0_tools/seedUsageSample.py            # create a sample database
    python 0_tools/seedUsageSample.py --force    # replace one that is there

Delete databases/inboxUsage.db afterwards to see the empty state again.
"""

import os
import random
import sqlite3
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import dbPaths  # noqa: E402

CITIES = [  # city, country, latitude, longitude, relative weight
    ('Reykjavik', 'IS', 64.15, -21.94, 10), ('Geneva', 'CH', 46.20, 6.14, 6), ('London', 'GB', 51.51, -0.13, 8),
    ('Boulder', 'US', 40.01, -105.27, 4), ('Odense', 'DK', 55.40, 10.39, 3), ('Sydney', 'AU', -33.87, 151.21, 2),
    ('Bengaluru', 'IN', 12.97, 77.59, 2), ('Lausanne', 'CH', 46.52, 6.63, 3),
]
WEEKS = 12


def main():
    path = dbPaths.dbPath(dbPaths.USAGE_DB)
    if os.path.exists(path):
        if '--force' not in sys.argv:
            sys.exit(f'{path} exists; use --force to replace it with sample data.')
        os.remove(path)
    rng = random.Random(1)   # the same sample every time
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE logins (day TEXT, city TEXT, country TEXT, latitude REAL, longitude REAL, logins INTEGER,'
                 ' PRIMARY KEY (day, city, country))')
    today = date.today()
    rows = []
    for offset in range(WEEKS * 7):
        day = (today - timedelta(days=offset)).isoformat()
        growth = 1 + (WEEKS * 7 - offset) / (WEEKS * 7)   # busier towards the present
        for city, country, latitude, longitude, weight in CITIES:
            count = int(rng.random() * weight * growth)
            if count:
                rows.append((day, city, country, latitude, longitude, count))
    conn.executemany('INSERT INTO logins VALUES (?, ?, ?, ?, ?, ?)', rows)
    conn.commit()
    conn.close()
    print(f'Wrote {len(rows)} SAMPLE rows to {path}')


if __name__ == '__main__':
    main()
