"""Human recording IDs are monotonic; LeRobot episode IDs stay independent."""
import json
import os
from pathlib import Path


def next_take_number(root):
    root = Path(root)
    highest = -1
    for parent in (root, root / "takes", root / ".bpx_pending"):
        if parent.is_dir():
            for item in parent.iterdir():
                if item.name.isascii() and item.name.isdigit():
                    highest = max(highest, int(item.name))
    # Include earlier successful recordings that predate takes/<number>.
    for pattern in (".bpx_commits/*.json", "data/chunk-*/episode_*.parquet"):
        for item in root.glob(pattern):
            name = item.stem[8:] if item.stem.startswith("episode_") else item.stem
            if name.isascii() and name.isdigit():
                highest = max(highest, int(name))
    counter = root / ".bpx_next_take.json"
    if counter.is_file():
        value = json.loads(counter.read_text(encoding="utf-8"))["next"]
        if type(value) is not int or value < 0:
            raise ValueError("invalid recording counter; refusing to reuse IDs")
        highest = max(highest, value - 1)
    return highest + 1


def reserve_take_number(root):
    """Caller holds the dataset's exclusive lock. Persist BEFORE creating a take."""
    root = Path(root)
    number = next_take_number(root)
    counter = root / ".bpx_next_take.json"
    temporary = counter.with_name(counter.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump({"next": number + 1}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(counter))
    return number
