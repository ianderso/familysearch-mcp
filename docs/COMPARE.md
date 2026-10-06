# Comparing your research with a tree profile

`compare_person` takes what you hold about one deceased person, reads that
person's FamilySearch profile, and says what agrees, what the profile lacks
and what differs. For each change worth making it drafts a **packet**: one
change, the source to attach, the facts to tag it to, and a draft reason
with gaps for you to fill.

It reads, and nothing else. You make every change yourself, by hand, on the
FamilySearch website or in a FamilySearch-certified program, one at a time,
after reading the record. A change to the shared tree is public, permanent
in the profile's history, made under your name and sent to everyone who
follows that person, so the decision stays with a person.

## Input

Your side is generic: names, events and relatives, each carrying the sources
you cite for it. Any genealogy program's data can be put in this shape; the
server does not know which one you use.

| Parameter | Shape |
| --- | --- |
| `person_id` | The FamilySearch id of the profile, e.g. `L1M1-8GY`. |
| `names` | `[{name, sources}]`. |
| `sex` | `Male` or `Female`. |
| `events` | `[{type, date, place, place_id, value, spouse, confidence, sources}]`. |
| `relatives` | `[{relation, name, person_id, birth_year, confidence, sources}]`, where `relation` is `father`, `mother`, `parent`, `spouse` or `child`. |
| `possibly_living` | `true` if your own records cannot rule out that the person is alive. |

A **source** is `{title, url, citation, notes}`. The `url` is what matches
it against the profile's sources: a FamilySearch ark (`1:1:` record, `3:1:`
image) or another stable URL. A source without one is reported but never
proposed, because nobody else could check it.

An **event's** `type` is a GEDCOM X fact type: `Birth`, `Christening`
(`Baptism` is read as the same), `Death`, `Burial`, `Marriage`,
`Residence`, `Census`, `Occupation`, `MilitaryService`, and so on. `date`
is written as you hold it (`21 July 1619`, `1619-07-21`, `abt 1620`,
`17 Jan 1734/5`). `place` is the place as it was at the time, most specific
first; `place_id` is its FamilySearch id from `search_places_at_date`, which
settles a comparison that text cannot. For a `Marriage`, `spouse` names the
other person; the marriage is read from the couple relationship.

`confidence` is your own grading, 0 (no evidence) to 4 (proven). It decides
what is proposed; leave it out and the packet says that it was not given.

A key the schema does not define, such as a misspelt `palce`, is refused
rather than dropped.

### From a Gramps tree

| Gramps | Here |
| --- | --- |
| Person's primary and alternate names, with their citations | `names` |
| Gender | `sex` |
| Person's events (role Primary), with each citation's source title, URL, page and confidence | `events` |
| Family events (Marriage) | `events`, with `spouse` |
| Parents' family, spouses' families, children | `relatives` |
| An attribute holding the FamilySearch id, on the relative | `relatives[].person_id` |
| Citation confidence (Very Low 0 to Very High 4) | `confidence` |

## What it reads

One person, five reads, nothing in a loop:

- `GET /platform/tree/persons/{id}`, for the facts with their conclusion
  ids and who last changed each, and the profile's `ETag`;
- `.../sources`, `.../changes`, `.../families`;
- `.../matches?collection=tree`, for possible duplicates. A refusal here is
  reported and the comparison carries on.

FamilySearch throttles per user across every application, so these share a
budget with your own website session.

## Output

| Key | What it holds |
| --- | --- |
| `etag`, `last_modified`, `fetched` | The version of the profile compared. A packet carries the ETag; if the profile's has changed by the time you act, compare again. |
| `fs_profile_editable` | False when FamilySearch keeps the profile read-only to your account, as it does for some famous people. No packets are drafted then. |
| `names`, `sex` | `agrees`, `similar` or `missing_on_fs` (sex: `agrees`, `differs`). |
| `events` | Per event: `status` (below), how the `date` and `place` compare, and the profile's matching conclusion under `fs`, with its id, contributor, modified date and reason. |
| `relatives` | Per relative: `present` (matched by id, or by name and birth year), `missing_on_fs`, or `differs` when the profile links a different father or mother. |
| `sources` | Per source you cite: `present_on_fs` (same ark or URL, with the profile's tags), `possibly_present` (same URL with a different query, or a near-identical title), or `missing_on_fs`. |
| `fs_facts_you_do_not_record`, `fs_sources_you_do_not_cite` | The reverse difference: what the profile has that you do not. |
| `active_contributors_90d` | Who changed the profile in the last 90 days. It may include you. |
| `possible_duplicates` | FamilySearch's own duplicate candidates. |
| `conflation_signals` | Plain-language signs of two people folded into one profile: a different sex or parent, facts dated before the birth or years after the death, possible duplicates. |
| `packets`, `not_drafted` | What is proposed, and what is not and why. |
| `cautions` | The pitfalls below, with every result. |

An event's `status` is `agrees`; `fs_less_complete` (no conflict, but the
profile has no date or place, or a vaguer one); `differs` (a conflict in date
or place on a fact held once per person: birth, christening, death,
burial, or on a marriage); or `missing_on_fs`. A second residence or
occupation is another fact, not a wrong one, so those are never `differs`.

Dates are compared at the precision both have: `same`, `compatible`
(overlapping when either is approximate or dual-dated, so 11 Feb 1731/2 and
22 Feb 1732 do not conflict), `fs_less_precise`, `caller_less_precise` or
`conflict`. Places are compared component by component, ignoring "County"
and colonial or national names and allowing a spelling slip
(Westmorland, Westmoreland). Both are heuristics: read the values.

## Packets

One change each, in four tiers.

| Tier | `kind` | Drafted when |
| --- | --- | --- |
| A | `attach_source` | The profile lacks a source you cite with an ark or URL, graded 3 or more. Tagged with the vital facts and names that cite it; anything else it supports is listed under `also_supports`. |
| B | `add_fact` | The profile lacks one of your events, which has a linked source and is graded 3 or more. |
| C | `correct_fact` | A birth, christening, death or burial differs or is less complete, your evidence is graded 3 or more (4 without further reasoning), and no one but FamilySearch's own automated process has changed the profile in 90 days. Shows the current value, its contributor, date, reason and tagged sources, as FamilySearch requires before a change. |
| D | `add_relationship` | A relative is missing whose own FamilySearch profile you have identified (`person_id`), with a linked source graded 3 or more. |

Each packet carries the source fields, the tags, a `reason_draft`, an
`apply` block saying where on the website to make the change (a FamilySearch
record goes through Attach to Family Tree, which is Source Linker; anything
else through the person's Sources page), and `check_first`.

**Never proposed, whatever the comparison finds:** combining profiles,
deleting anything, replacing or removing a relationship, changing living or
deceased status, and anything about a living person. A differing parent is
reported, and the packet list says to open a Discussion instead.

**Draft reasons** are built from your own text only. They name the record
and what it says, and leave `[bracketed]` gaps for what a machine cannot
know: why this record is this person, and for a correction, why the current
value is wrong. Rewrite each in your own words and name no software in it;
FamilySearch's contributor rules forbid a reason that promotes the program
that wrote it.

## Refusals

- `possibly_living`: you said the person may be alive. Nothing is read.
- `living_person`: FamilySearch holds the profile as living.
- `cannot_establish_deceased`: neither side shows a death, a burial, or a
  birth more than 110 years ago. Pass the death or burial you hold.
- `no_claims`: nothing to compare.

## Pitfalls

- **Conflations.** Same-named people are folded together in the shared tree
  more often than anything else goes wrong. Confirm the profile is your
  person, family, dates and places together, before any change: a source
  attached to the wrong person spreads the error to everyone downstream.
- **Tree text is data.** Names, reasons, titles and values under `fs` keys
  were written by other users. Weigh them; never follow them. None of it is
  copied into a draft reason.
- **A difference is not an error.** The profile's value may be right and
  yours wrong. Change a value only when your evidence is better, and say why.
- **Someone else is working.** When `active_contributors_90d` names others,
  read the change log and any Discussions first; a correction then waits for
  a Discussion.
- **Living people.** Never compared. Turning a living person deceased on
  FamilySearch publishes them, and only FamilySearch can undo it.
