"""Integration stages (TD-13): code orchestrates, the model makes small decisions.

chunk (packet.py) → extract → merge in source → resolve → plan → patch → apply
(edits.py) → autolink → finish (integrate.py). Each stage takes and returns plain
dataclasses that serialise to JSON, so a stage's output can be inspected with
`mneme-wiki integrate <packet> --stage <name> --out x.json`.
"""
