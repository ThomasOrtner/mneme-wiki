"""M0 spike: micro-benchmark for the resolve decision on hand-made pairs.

The full runs showed resolve is the weak stage (strict prompt: never merges; loose prompt:
merges related-but-different things). This isolates the decision: one new subject vs ONE
candidate, yes/no, under three variants. Pairs come from real cases in the spike runs.

Usage: python spike/resolve_bench.py [--model qwen3:14b]
"""

from __future__ import annotations

import argparse
import json
import time

import ollama

# (new name, new description, candidate title, candidate aliases, candidate description, same?)
PAIRS = [
    ("Strategic Planning", "Planning process that prepares future rover activities before tactical planning.",
     "Strategic Planning Cycle", [], "Operational planning process that progressively prepares future Rover activities.", True),
    ("RFM-EXM", "The ExoMars Rosalind Franklin rover mission.",
     "ExoMars Rosalind Franklin Mission", ["RFM"], "ESA rover mission to Mars.", True),
    ("Trajectory", "Rover path, planned or executed, stored on the DAR.",
     "Traverse", ["notional traverse"], "Route of the rover across the terrain, planned or executed.", True),
    ("RSOWG", "Rover science operations working group whose members plan science.",
     "SOWG", [], "Science Operations Working Group of the rover mission.", True),
    ("m20", "NASA's Mars 2020 rover mission, used as a reference for MMGIS.",
     "Mars 2020", ["Perseverance"], "NASA Mars rover mission launched in 2020.", True),
    ("TK", "Role responsible for creating and maintaining official targets.",
     "Target Keeper", [], "Role that creates official targets in MMGIS and synchronises them with the DAR.", True),
    ("SKP-FT", "Field trials of the SKP activity giving access to scientists.",
     "SKP Field Trials", [], "Field trial campaign of the SKP project.", True),
    ("Integrated Activity Plan", "Plan combining engineering and science partial plans for a complete Sol.",
     "Integrated Plan", [], "Complete candidate Activity Plan covering the full duration of a single Sol.", True),
    ("Digital Terrain Model", "Elevation model of the terrain.",
     "DTM", [], "Terrain elevation data loaded as tiles in MMGIS.", True),
    ("Pro3D", "3D visualisation tool used in the ROCC.",
     "PRo3D", [], "Interactive 3D viewer for planetary surface reconstructions.", True),
    # different things (all were wrongly merged or are classic confusions)
    ("Integrated Plan", "Complete candidate Activity Plan covering a full Sol.",
     "Activity Plan", ["AP"], "Operational product describing the sequence of activities the Rover executes in a Sol.", False),
    ("Uploaded Plan", "Validated plan delivered for uplink to the Rover.",
     "Validated Plan", [], "Activity Plan formally verified and approved for execution.", False),
    ("Planning Target", "Target identified during planning before any rover observation.",
     "Target", [], "A location or object of operational or scientific interest.", False),
    ("Local Target", "Target observed by the rover with confirmed position.",
     "Planning Target", [], "Target identified during planning before any rover observation.", False),
    ("dar_ci", "Command line tool to query and fetch data from the DAR.",
     "DAR", [], "Archive that stores the operational entities generated during rover planning and operations.", False),
    ("Notional Traverse", "Rough traverse defined by the long-term planner.",
     "Long-Term Planner", [], "Role defining notional traverses and long-term exploration strategy.", False),
    ("User Authentication", "Options for authenticating users in the deployed environment.",
     "ExoMars Rosalind Franklin Mission", ["RFM"], "ESA rover mission to Mars.", False),
    ("Target Promotion", "Process by which a suggested target becomes an actual target once named.",
     "Target", [], "A location or object of operational or scientific interest.", False),
    ("Regions of Interest", "Named regions acting as strategic targets.",
     "Target", [], "A location or object of operational or scientific interest.", False),
    ("Wedge Draw Tool", "Proposed MMGIS tool for drawing camera viewing wedges.",
     "Draw Tool", [], "MMGIS tool for drawing and publishing features.", False),
    ("Tactical Planning Cycle", "Process turning activity plans into validated commands for Sol N.",
     "Strategic Planning Cycle", [], "Process preparing future rover activities over several horizons.", False),
    ("Forbidden Area", "Polygon area the rover must stay away from.",
     "Area of Interest", [], "Polygon area that possibly contains points of interest.", False),
]

SCHEMA = {"type": "object", "properties": {"reason": {"type": "string"}, "same": {"type": "boolean"}},
          "required": ["reason", "same"]}

SYSTEM = """Decide whether two wiki subjects are the SAME thing, i.e. one page would describe both.
Same: the same thing under another name, abbreviation, short form, spelling, or plural.
Different: a part, a subtype, an instance, a step, a related tool, a role related to it, or something it is used with.
Examples: "Local Target" vs "Target" -> different (subtype). "dar_ci" vs "DAR" -> different (tool for it).
"AP" vs "Activity Plan" -> same (abbreviation). "Tactical Planning" vs "Tactical Planning Cycle" -> same (short form).
Give a short reason first, then the answer."""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3:14b")
    a = ap.parse_args()
    client = ollama.Client(host="http://localhost:11434")
    results = {}
    for think in (False, True):
        label = f"pairwise {'think' if think else 'no-think'}"
        tp = fp = fn = tn = 0
        lat = 0.0
        wrong = []
        for new, nd, cand, cal, cd, same in PAIRS:
            user = (f"A: {new}\n   {nd}\nB: {cand} (aliases: {cal})\n   {cd}\n\nAre A and B the same thing?")
            t0 = time.time()
            r = client.chat(model=a.model, messages=[{"role": "system", "content": SYSTEM},
                                                     {"role": "user", "content": user}],
                            format=SCHEMA, think=think, options={"temperature": 0, "num_ctx": 4096})
            lat += time.time() - t0
            ans = json.loads(r.message.content)["same"]
            tp += ans and same
            fp += ans and not same
            fn += (not ans) and same
            tn += (not ans) and not same
            if ans != same:
                wrong.append(f"{new} vs {cand}: said {'same' if ans else 'different'}")
        results[label] = {"precision": round(tp / max(tp + fp, 1), 2), "recall": round(tp / max(tp + fn, 1), 2),
                          "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                          "mean_latency_s": round(lat / len(PAIRS), 1), "wrong": wrong}
        print(label, json.dumps(results[label], indent=1), flush=True)


if __name__ == "__main__":
    main()
