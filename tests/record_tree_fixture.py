"""Record a tree person's responses as a test fixture, with contributors scrubbed.

Not part of the suite. ``compare_person`` reads five responses for one
person, and its tests replay them from ``tests/fixtures/tree/``. Run this by
hand, with a token, to record or refresh one::

    uv run python -m tests.record_tree_fixture L1M1-8GY

Record only long-dead historical people whose profiles are public. The
subject and their family keep their names; that is the point of the
fixture. Everyone who *edited* the profile does not: contributor names and
agent ids are replaced with invented ones, every reason they typed is
replaced, and citations and notes are dropped. Long fact values are cut
short and the change log is cut to its most recent entries, so a fixture
stays small enough to read.

The token is found the way the server finds it: ``FS_ENV_FILE``, or the
nearest ``.env`` upward. Five reads, one person.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from familysearch_mcp.client import GEDCOMX_ATOM_JSON, FamilySearchClient
from familysearch_mcp.config import load_config, token_from_env_file

OUT = Path(__file__).parent / "fixtures" / "tree"

#: Change-log entries kept, most recent first.
CHANGES_KEPT = 12

#: The longest fact value kept; a life sketch runs to pages.
VALUE_LIMIT = 200

#: FamilySearch's own automated changes carry this name. It is not a person.
SYSTEM = "FamilySearch"


class Scrubber:
    """Replaces contributor identities consistently across one recording."""

    def __init__(self) -> None:
        self.agents: dict[str, str] = {}
        self.names: dict[str, str] = {}

    def agent(self, agent_id: str | None) -> str:
        """An invented agent id standing for a real one."""
        key = agent_id or ""
        if key not in self.agents:
            self.agents[key] = f"AGENT-{len(self.agents) + 1:03d}"
        return self.agents[key]

    def name(self, name: str) -> str:
        """An invented contributor name, keeping the system's own."""
        if name == SYSTEM:
            return name
        if name not in self.names:
            self.names[name] = f"Contributor {len(self.names) + 1}"
        return self.names[name]

    def attribution(self, attribution: dict | None) -> dict | None:
        """Keep when a conclusion changed; replace who changed it and why."""
        if not isinstance(attribution, dict):
            return None
        out: dict = {"modified": attribution.get("modified")}
        agent = (attribution.get("contributor") or {}).get("resourceId")
        if agent:
            fake = self.agent(agent)
            out["contributor"] = {
                "resource": f"https://api.familysearch.org/platform/users/agents/{fake}",
                "resourceId": fake,
            }
        if attribution.get("changeMessage"):
            out["changeMessage"] = "A reason a contributor gave."
        return out


def _fact(entry: dict, scrub: Scrubber) -> dict:
    kept = {k: entry[k] for k in ("id", "type", "date", "place", "value") if k in entry}
    if isinstance(kept.get("value"), str) and len(kept["value"]) > VALUE_LIMIT:
        kept["value"] = kept["value"][:VALUE_LIMIT]
    if "attribution" in entry:
        kept["attribution"] = scrub.attribution(entry["attribution"])
    return kept


def _person(entry: dict, scrub: Scrubber) -> dict:
    display = entry.get("display") or {}
    out = {
        "id": entry.get("id"),
        "living": entry.get("living"),
        "gender": {k: v for k, v in (entry.get("gender") or {}).items() if k == "type"},
        "names": [
            {
                "type": name.get("type"),
                "preferred": name.get("preferred"),
                "nameForms": [{"fullText": f.get("fullText")} for f in name.get("nameForms") or []],
            }
            for name in entry.get("names") or []
        ],
        "facts": [_fact(f, scrub) for f in entry.get("facts") or []],
        "display": {k: display[k] for k in ("name", "gender", "lifespan") if k in display},
    }
    if "personInfo" in entry:
        out["personInfo"] = entry["personInfo"]
    if "sources" in entry:
        out["sources"] = [
            {
                "id": ref.get("id"),
                "descriptionId": ref.get("descriptionId"),
                "description": ref.get("description"),
                "tags": ref.get("tags") or [],
                "attribution": scrub.attribution(ref.get("attribution")),
            }
            for ref in entry["sources"]
        ]
    return out


def scrub_person(document: dict, scrub: Scrubber) -> dict:
    """The person read: the subject only, without links or evidence."""
    return {"persons": [_person(p, scrub) for p in document.get("persons") or []]}


def scrub_sources(document: dict, scrub: Scrubber) -> dict:
    """Sources: titles and arks kept; citations, notes and authors dropped."""
    return {
        "persons": [
            {"id": p.get("id"), "sources": _person(p, scrub).get("sources", [])}
            for p in document.get("persons") or []
        ],
        "sourceDescriptions": [
            {k: sd[k] for k in ("id", "about", "titles", "resourceType") if k in sd}
            for sd in document.get("sourceDescriptions") or []
        ],
    }


def scrub_changes(document: dict, scrub: Scrubber) -> dict:
    """The most recent changes, with who made them replaced."""
    entries = []
    for item in (document.get("entries") or [])[:CHANGES_KEPT]:
        contributors = []
        for who in item.get("contributors") or []:
            agent = (who.get("uri") or "").rstrip("/").rsplit("/", 1)[-1]
            fake = scrub.agent(agent)
            contributors.append(
                {
                    "name": scrub.name(who.get("name") or ""),
                    "uri": f"https://api.familysearch.org/platform/users/agents/{fake}",
                }
            )
        entries.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "updated": item.get("updated"),
                "contributors": contributors,
                "changeInfo": [
                    {k: info[k] for k in ("operation", "objectType") if k in info}
                    for info in item.get("changeInfo") or []
                ],
            }
        )
    return {"entries": entries}


def _relative(entry: dict, scrub: Scrubber) -> dict:
    """A relative: who they are, without their own facts and sources."""
    shaped = _person(entry, scrub)
    return {k: v for k, v in shaped.items() if k not in ("facts", "sources", "personInfo")}


def scrub_families(document: dict, subject: str, scrub: Scrubber) -> dict:
    """The subject's own couples and parent-child links, and those people."""
    couples = [
        {
            "id": rel.get("id"),
            "type": rel.get("type"),
            "person1": rel.get("person1"),
            "person2": rel.get("person2"),
            "facts": [_fact(f, scrub) for f in rel.get("facts") or []],
        }
        for rel in document.get("relationships") or []
        if subject
        in {
            (rel.get("person1") or {}).get("resourceId"),
            (rel.get("person2") or {}).get("resourceId"),
        }
    ]
    links = [
        {k: rel[k] for k in ("id", "child", "parent1", "parent2") if k in rel}
        for rel in document.get("childAndParentsRelationships") or []
        if subject
        in {(rel.get(k) or {}).get("resourceId") for k in ("child", "parent1", "parent2")}
    ]
    wanted = {subject}
    for rel in couples:
        wanted |= {(rel[k] or {}).get("resourceId") for k in ("person1", "person2")}
    for rel in links:
        wanted |= {(rel.get(k) or {}).get("resourceId") for k in ("child", "parent1", "parent2")}
    people = [_relative(p, scrub) for p in document.get("persons") or [] if p.get("id") in wanted]
    return {"persons": people, "relationships": couples, "childAndParentsRelationships": links}


def scrub_matches(document: dict, scrub: Scrubber) -> dict:
    """Duplicate candidates: the candidate people, scrubbed like the rest."""
    return {
        "entries": [
            {
                "id": item.get("id"),
                "score": item.get("score"),
                "content": {
                    "gedcomx": {
                        "persons": [
                            _person(p, scrub)
                            for p in ((item.get("content") or {}).get("gedcomx") or {}).get(
                                "persons"
                            )
                            or []
                        ]
                    }
                },
            }
            for item in document.get("entries") or []
        ]
    }


async def record(person_id: str) -> Path:
    """Read one person's five responses and write the scrubbed fixture."""
    config = load_config()
    if config.env_file:
        config.access_token = token_from_env_file(config.env_file) or config.access_token
    scrub = Scrubber()
    base = f"/platform/tree/persons/{person_id}"
    async with FamilySearchClient(config) as client:
        person, validators = await client.get_with_validators(base)
        sources = await client.get(f"{base}/sources")
        changes = await client.get(f"{base}/changes", accept=GEDCOMX_ATOM_JSON)
        families = await client.get(f"{base}/families")
        matches = await client.get(
            f"{base}/matches", accept=GEDCOMX_ATOM_JSON, collection="tree", count=5
        )
    fixture = {
        "person_id": person_id,
        "validators": validators,
        "person": scrub_person(person, scrub),
        "sources": scrub_sources(sources, scrub),
        "changes": scrub_changes(changes, scrub),
        "families": scrub_families(families, person_id, scrub),
        "matches": scrub_matches(matches, scrub),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"{person_id}.json"
    target.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def main() -> int:
    """Parse arguments and record."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("person_id", help="a long-dead historical person's tree id")
    args = parser.parse_args()
    print(f"wrote {asyncio.run(record(args.person_id))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
