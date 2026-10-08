"""Environment forking (Milestone 7): cheap file-copy snapshots instead
of reseeding every mock service's SQLite state from scratch for every
simulation (Milestone 6's stand-in, see DECISIONS.md decision 21).

Plain file copies, not PostgreSQL template databases or a copy-on-write
filesystem - the mock services already are plain SQLite files, and a
copy of a handful of small files needs no new infrastructure. This is
the project's own "Snapshot strategy" design decision (DECISIONS.md),
made concretely rather than left abstract.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def fork_environment(template_dir: Path, target_dir: Path) -> None:
    """Copies every *.db file from a template directory into a fresh
    target directory - the fork. Isolated from the template and from
    every other fork: nothing written to target_dir ever touches
    template_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for db_file in sorted(template_dir.glob("*.db")):
        shutil.copy2(db_file, target_dir / db_file.name)
