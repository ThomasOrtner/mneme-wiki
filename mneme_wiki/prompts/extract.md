You extract knowledge from one chunk of a document, for a personal wiki.

Return the important subjects the chunk says something substantive about:
- entities: people, organisations, teams, roles, projects, missions, systems, software tools, instruments, places, documents
- concepts: ideas, methods, processes, data types, terms

For each subject:
- name: the canonical full name (e.g. "Rover Operations Control Centre" rather than "ROCC") if the full form is given in the text or the known-pages list; otherwise the name as written. If the subject matches a known wiki page, use exactly that page's title.
- aliases: only other names for exactly this subject: abbreviations, other spellings, translations, short forms. Never the names of its parts, its parent, its owner or operator, or related or sibling things (e.g. a mission's rover or camera is not an alias of the mission); those belong in claims.
- description: one neutral sentence saying what it is.
- claims: 1-6 self-contained factual statements from the chunk about this subject. Each claim must be understandable on its own (no "it", "this"), at most 35 words, and must be supported by the chunk.

entity vs concept:
- entity = one specific, named thing that exists once: a person, a team, an organisation, a mission, a software system, an instrument, a place. Set entity_kind accordingly (never "other" if one of the kinds fits).
- concept = a type, category, process, method, data type or term that can have many instances (e.g. "Activity Plan", "Target", "Waypoint", "Tactical Planning Cycle"). entity_kind "other".

Only subjects that deserve their own wiki page. Field names, attribute values, enumeration values, file names, examples and individual plan steps are NOT subjects: put them as claims on their parent subject (e.g. the field "Load_Status" is a claim about "Integrated Plan"; POWER/TIME/DATA VOLUME are claims about "Planning Resources").

Rules: use only information in the chunk. Skip passing mentions, URLs, file names, coordinates, shell commands, phone numbers. At most 15 subjects; cover every subject the chunk defines or explains.
