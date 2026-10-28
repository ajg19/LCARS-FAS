"""Installs the reference databases a deploy uploaded, and publishes the
site files built from them. Run on the server by 0_tools/deployToGoDaddy.sh.

Decision D of 0_documentation/plans/dbRefactorPlan.md: ingestionGroundSegment.db
(from Al's master spreadsheet) and ingestionSkyCatalogue.db (from the
star catalogues) are built on the laptop and committed; the deploy
excludes databases/ from its sync, so the server's own data can never be
overwritten, and uploads these two separately into UPLOAD_DIR. This
script then, for each one:
  - leaves it alone if it is identical to the installed copy;
  - otherwise checks it opens as a database, swaps it into databases/
    (os.replace -- atomic) and publishes its site file (publishSite),
under the shared writers' lock, so no ingestion or publish overlaps.
The uploads are removed afterwards either way.

    python scripts/installReferenceDbs.py UPLOAD_DIR

Before the server is migrated (plan step 12) there is no databases/
folder and no site files: the uploads are discarded and the server keeps
serving its existing reference databases.
"""

import hashlib
import os
import shutil
import sqlite3
import sys

import dbPaths
from dbPaths import DB_DIR, DB_DIR_NAME, GROUND_SEGMENT_DB, SKY_DB, dbPath
from runIngestion import LOCK_NAME, Lock

# uploaded file name -> site kind it feeds
REFERENCE_DBS = {GROUND_SEGMENT_DB: 'groundSegment', SKY_DB: 'sky'}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def opensAsDatabase(path):
    try:
        db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        ok = db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        db.close()
        return ok
    except sqlite3.Error:
        return False


def install(uploadDir, publish=None):
    """Returns [(file, outcome)]. publish is injectable for tests."""
    results = []
    if dbPaths.LEGACY or os.path.basename(DB_DIR) != DB_DIR_NAME or not os.path.isdir(DB_DIR):
        results.append(('*', 'server not migrated yet -- uploads discarded'))
        return results
    if publish is None:
        from publishSite import publish
    with Lock(os.path.join(DB_DIR, LOCK_NAME)):
        for name, kind in REFERENCE_DBS.items():
            upload = os.path.join(uploadDir, name)
            if not os.path.exists(upload):
                results.append((name, 'not uploaded'))
                continue
            target = dbPath(name)
            if os.path.exists(target) and digest(upload) == digest(target):
                results.append((name, 'unchanged'))
                continue
            if not opensAsDatabase(upload):
                results.append((name, 'REJECTED -- not a sound database; installed copy kept'))
                continue
            staged = target + '.new'
            shutil.copy2(upload, staged)
            os.replace(staged, target)
            try:
                counts = publish(kind)
                results.append((name, 'installed; published ' + ', '.join(f'{t} {n}' for t, n in counts.items())))
            except Exception as error:
                results.append((name, f'installed; publish REFUSED -- {type(error).__name__}: {error}'))
    return results


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print('usage: installReferenceDbs.py UPLOAD_DIR', file=sys.stderr)
        return 2
    uploadDir = argv[0]
    try:
        results = install(uploadDir)
    finally:
        shutil.rmtree(uploadDir, ignore_errors=True)
    for name, outcome in results:
        print(f'  reference {name}: {outcome}')
    return 1 if any('REJECTED' in o or 'REFUSED' in o for _, o in results) else 0


if __name__ == '__main__':
    sys.exit(main())
