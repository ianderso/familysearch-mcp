"""Record a FamilySearch Catalog entry as a test fixture, with names scrubbed.

Not part of the suite. ``get_catalog_entry`` reads one catalog entry and,
for each item it returns, that image group's node on the storage host. Its
tests replay both from ``tests/fixtures/catalog/``. Run this by hand, with a
token, to record or refresh one::

    uv run python -m tests.record_catalog_fixture 3154151 --items 40

The entry is cut to its first ``--items`` films. A probate or court entry
describes each file by the people it concerns, so every word of an item's
description outside the catalogue's own vocabulary is replaced with an
invented one, the same way each time it recurs; numbers, years and
punctuation are kept, because filtering on them is what the tests exercise.
The title, authors, subjects and notes are kept as they are, so record only
an entry whose description names no private person.

The storage host's answer is recorded for the first film this account may
view and the first it may not. The token is found the way the server finds
it: ``FS_ENV_FILE``, or the nearest ``.env`` upward. It is never written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from familysearch_mcp.client import FamilySearchClient
from familysearch_mcp.config import load_config
from familysearch_mcp.shape import pad_dgs

OUT = Path(__file__).parent / "fixtures" / "catalog"

#: Words a description keeps: the catalogue's vocabulary, never a person's.
VOCABULARY = frozenset(
    """
    probate records record summaries summary box no no. file files guardianship
    guardenship minor minors vs vs. et al al. and & of in to the a estate estates
    company county court magistrate cancellation general index docket journal
    register volume vol vol. book case cases furnas
    """.split()
)

#: Invented words to put in place of a person's, used in order.
INVENTED = """
    Pettibone Thackeray Chesebrough Ezra Lydia Amos Abigail Hezekiah Prudence
    Obadiah Thankful Jedidiah Mehitable Zebulon Keziah Elnathan Submit Asahel
    Experience Ebenezer Huldah Josiah Lovina Phineas Sophronia Barzillai Tryphena
    Ichabod Philura Cyrenius Lucretia Bethuel Parthenia Elihu Rhoda Zadock
    Desire Ozias Patience Silas Temperance Gideon Waitstill Reuben Charity
    Hiram Electa Lemuel Mercy Abijah Clarissa Eliphalet Dorcas Jabez Remember
    Ashbel Wealthy Ephraim Lodema Thaddeus Orpha Nehemiah Achsah Darius Polly
    Erastus Philena Ithamar Roxana Simeon Zeruiah Elkanah Jerusha Lyman Sabra
    Zenas Anstress Hosea Persis Benajah Eunice Lorenzo Hepzibah Calvin Mindwell
    Augustus Lucinda Cephas Thirza Elias Fidelia Orrin Melinda Isaac Hannah
    Marvin Lavinia Stephen Delight Truman Betsey Nathan Asenath Joel Cynthia
""".split()

#: A word in a description: it starts with a letter, and may end in a full
#: stop, which keeps an initial ("R.") whole.
WORD = re.compile(r"[^\W\d_][\w']*\.?")


class Scrubber:
    """Replaces the words of people's names consistently across one recording."""

    def __init__(self) -> None:
        self.words: dict[str, str] = {}
        self.initials: dict[str, str] = {}

    def word(self, match: re.Match) -> str:
        """Keep a vocabulary word; replace anything else with an invented one."""
        token = match.group(0)
        if token.lower() in VOCABULARY or token.rstrip(".").lower() in VOCABULARY:
            return token
        if re.fullmatch(r"[A-Za-z]\.", token):
            if token not in self.initials:
                self.initials[token] = f"{chr(ord('A') + len(self.initials) % 26)}."
            return self.initials[token]
        stem, dot = (token[:-1], ".") if token.endswith(".") else (token, "")
        if stem not in self.words:
            n = len(self.words)
            self.words[stem] = INVENTED[n % len(INVENTED)] + ("" if n < len(INVENTED) else str(n))
        return self.words[stem] + dot

    def description(self, text: str) -> str:
        """A description with every name in it replaced."""
        return WORD.sub(self.word, text or "")


async def record(catalog_id: str, items: int) -> None:
    """Record one catalog entry and two storage-host answers."""
    config = load_config()
    async with FamilySearchClient(config) as client:
        entry = dict(await client.catalog_entry(catalog_id))
        notes = entry.get("film_note") or []
        notes = (notes if isinstance(notes, list) else [notes])[:items]
        scrubber = Scrubber()
        entry["film_note"] = [
            {**note, "text": scrubber.description(note.get("text") or "")} for note in notes
        ]
        wanted = {200, 403}
        groups = {}
        for note in notes:
            dgs = pad_dgs(note.get("digital_film_no"))
            if not dgs or not wanted:
                continue
            status, body = await client.image_group(dgs)
            if status in wanted:
                wanted.discard(status)
                groups[dgs] = {"status": status, "body": body}

    text = json.dumps({"source": entry}, indent=1, ensure_ascii=False) + "\n"
    das = json.dumps(groups, indent=1, ensure_ascii=False) + "\n"
    token = config.access_token or ""
    if token and (token in text or token in das):
        raise SystemExit("The token appeared in a response; nothing was written.")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{catalog_id}.json").write_text(text, encoding="utf-8")
    (OUT / f"{catalog_id}-image-groups.json").write_text(das, encoding="utf-8")
    print(f"wrote {len(notes)} items and {len(groups)} image groups for catalog {catalog_id}")


def main() -> None:
    """Parse arguments and record."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("catalog_id", help="the catalog number, e.g. 3154151")
    parser.add_argument("--items", type=int, default=40, help="films to keep (default 40)")
    args = parser.parse_args()
    asyncio.run(record(args.catalog_id, args.items))


if __name__ == "__main__":
    main()
