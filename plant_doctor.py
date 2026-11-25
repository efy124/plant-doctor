"""
plant_doctor.py - Command-line interface for the Plant Doctor expert system.

ICT206 Intelligent Systems project - E. Sioras

Usage
    python plant_doctor.py              interactive consultation
    python plant_doctor.py --demo       replay the example from the proposal
    python plant_doctor.py --answers my_plant.json   non-interactive run
    python plant_doctor.py --check      validate the knowledge base only

During the interview type the option number, or:
    u = don't know     w = why are you asking?     h = help
    b = back (undo the last answer)               q = quit
"""

import argparse
import datetime
import json
import os
import sys
import textwrap

from engine import (InferenceEngine, KnowledgeBase, UNKNOWN, confidence_label,
                    diagnose)

WIDTH = 78
HERE = os.path.dirname(os.path.abspath(__file__))


def wrap(text, indent=""):
    return textwrap.fill(text, WIDTH, initial_indent=indent, subsequent_indent=indent)


def rule_line(char="-"):
    return char * WIDTH


# --------------------------------------------------------------------------
# Interview
# --------------------------------------------------------------------------
def explain_why(eng, attr):
    print()
    print(wrap("I am asking about '%s' because it can confirm or rule out:" % attr))
    seen = []
    for r in eng.relevant_rules(attr):
        then = r["then"]
        if then["attr"] == "diagnosis":
            target = eng.kb.diagnosis_name(then["value"])
        else:
            target = "the intermediate fact '%s'" % then["attr"]
        direction = "evidence FOR" if r["cf"] > 0 else "evidence AGAINST"
        line = "  - %s (%s, rule %s): %s" % (target, direction, r["id"], r.get("note", ""))
        if line not in seen:
            seen.append(line)
    for line in seen[:8]:
        print(textwrap.fill(line, WIDTH, subsequent_indent="      "))
    if len(seen) > 8:
        print("  ... and %d more rule(s)." % (len(seen) - 8))
    print()


def ask(eng, attr, number):
    q = eng.kb.questions[attr]
    keys = list(q["options"].keys())
    while True:
        print()
        print(wrap("Q%d. %s" % (number, q["text"])))
        for i, k in enumerate(keys, 1):
            print(wrap("%d) %s" % (i, q["options"][k]), "   "))
        print("   [u] don't know   [w] why?   [h] help   [b] back   [q] quit")
        try:
            raw = input("> ").strip().lower()
        except EOFError:
            return "quit"
        if raw in ("q", "quit", "exit"):
            return "quit"
        if raw in ("b", "back"):
            return "back"
        if raw in ("w", "why"):
            explain_why(eng, attr)
            continue
        if raw in ("h", "help", "?"):
            print(wrap(q.get("help", "Choose the option that best matches what you see. "
                                     "If you are not sure, type u.")))
            continue
        if raw in ("u", "unknown", "dont know", "don't know"):
            return UNKNOWN
        if raw.isdigit() and 1 <= int(raw) <= len(keys):
            return keys[int(raw) - 1]
        if raw in keys:
            return raw
        print("  Please type a number from 1 to %d (or u / w / h / b / q)." % len(keys))


def interview(eng):
    """Run the goal-driven interview. Returns False if the user quit."""
    number = 1
    while True:
        attr = eng.next_question()
        if attr is None:
            return True
        result = ask(eng, attr, number)
        if result == "quit":
            return False
        if result == "back":
            undone = eng.undo()
            if undone is None:
                print("  (Nothing to go back to.)")
            else:
                number = max(1, number - 1)
            continue
        eng.set_answer(attr, result)
        number += 1


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def build_report(eng, show_how=False):
    kb = eng.kb
    out = []
    res = eng.conclusion()
    out.append(rule_line("="))
    out.append("PLANT DOCTOR - DIAGNOSIS")
    out.append(rule_line("="))
    if res["primary"] is None:
        out.append(wrap("I could not reach a confident diagnosis from the information "
                        "given. Check the roots and the undersides of leaves, then try "
                        "again - or take a photo and a leaf sample to a local nursery."))
        weak = [kv for kv in eng.ranked_diagnoses() if kv[1] > 0.1]
        if weak:
            out.append("")
            out.append("Weak leads worth checking (not enough evidence yet):")
            for key, cf in weak[:3]:
                out.append("  - %s (CF %.2f)" % (kb.diagnosis_name(key), cf))
        out.append(rule_line("="))
        return "\n".join(out)

    def block(key, cf, heading):
        d = kb.diagnoses[key]
        out.append("")
        out.append("%s: %s" % (heading, d["name"]))
        out.append("Confidence: %s (certainty factor %.2f)" % (confidence_label(cf), cf))
        out.append(wrap("Why: " + d["explanation"]))
        out.append("What to do:")
        for a in d["actions"]:
            out.append(textwrap.fill("- " + a, WIDTH, initial_indent="  ",
                                     subsequent_indent="    "))
        if show_how:
            out.append("How I reached this conclusion:")
            for line in eng.explain_how(key):
                out.append(textwrap.fill(line, WIDTH, initial_indent="  ",
                                         subsequent_indent="      "))

    block(res["primary"][0], res["primary"][1], "MOST LIKELY PROBLEM")
    for key, cf in res["co"]:
        block(key, cf, "ALSO LIKELY (combined problem)")
    if res["other"]:
        out.append("")
        out.append("Other possibilities (low confidence):")
        for key, cf in res["other"]:
            out.append("  - %s (CF %.2f)" % (kb.diagnosis_name(key), cf))
    out.append("")
    out.append(wrap("Advice is based on university extension guidance (UC IPM, Iowa State, "
                    "Univ. of Maryland). If symptoms continue after correcting the cause, "
                    "seek advice from a nursery or horticulturist."))
    out.append(rule_line("="))
    return "\n".join(out)


def answers_summary(eng):
    lines = ["Your answers:"]
    for attr in eng.history:
        v = eng.answers[attr]
        txt = "don't know" if v is UNKNOWN else eng.kb.questions[attr]["options"][v]
        lines.append("  %-18s %s" % (attr, txt))
    return "\n".join(lines)


def save_report(eng):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = os.path.join(os.getcwd(), "diagnosis_%s.txt" % stamp)
    with open(name, "w", encoding="utf-8") as fh:
        fh.write(build_report(eng, show_how=True))
        fh.write("\n\n")
        fh.write(answers_summary(eng))
        fh.write("\n")
    print("Saved to %s" % name)


def after_menu(eng):
    while True:
        print()
        print("[h] how did you decide?   [a] show my answers   [s] save report   "
              "[r] new plant   [q] quit")
        try:
            c = input("> ").strip().lower()
        except EOFError:
            return "quit"
        if c == "h":
            res = eng.conclusion()
            keys = []
            if res["primary"]:
                keys = [res["primary"][0]] + [k for k, _ in res["co"]]
            if not keys:
                print("No rules reached the reporting threshold.")
            for k in keys:
                print()
                print("Reasoning for: %s" % eng.kb.diagnosis_name(k))
                for line in eng.explain_how(k):
                    print(textwrap.fill(line, WIDTH, initial_indent="  ",
                                        subsequent_indent="      "))
        elif c == "a":
            print(answers_summary(eng))
        elif c == "s":
            save_report(eng)
        elif c == "r":
            return "restart"
        elif c == "q":
            return "quit"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
DEMO_ANSWERS = {   # the example scenario from the project proposal
    "plant_type": "tropical_foliage", "leaf_yellowing": "lower_leaves",
    "leaf_browning": "none", "wilting": "no", "leaf_drop": "no",
    "growth": "normal", "speckled_leaves": "no", "soil_moisture": "soggy",
    "watering_frequency": "often", "drainage": "good", "light_level": "low",
    "recent_move": "none", "temperature": "normal", "humidity": "normal",
    "fertiliser": "normal", "soil_crust": "no", "stem_base": "firm",
    "roots": "not_checked", "rot_smell": "no", "pests_seen": "no",
    "white_powder": "no",
}


def run_batch(kb, answers, show_how=True):
    eng, asked = diagnose(kb, answers)
    print(answers_summary(eng))
    print("(%d of %d possible questions were needed)" % (len(asked), len(kb.questions)))
    print()
    print(build_report(eng, show_how=show_how))
    return eng


def main(argv=None):
    p = argparse.ArgumentParser(description="Plant Doctor - indoor plant problem expert system")
    p.add_argument("--kb", default=os.path.join(HERE, "knowledge_base.json"),
                   help="path to the knowledge base JSON file")
    p.add_argument("--demo", action="store_true", help="run the proposal's example scenario")
    p.add_argument("--answers", help="JSON file of answers for a non-interactive run")
    p.add_argument("--check", action="store_true", help="validate the knowledge base and exit")
    args = p.parse_args(argv)

    try:
        kb = KnowledgeBase(args.kb)
    except (ValueError, OSError) as e:
        print("Could not load knowledge base: %s" % e)
        return 1

    if args.check:
        print("Knowledge base OK: %d questions, %d rules, %d diagnoses." %
              (len(kb.questions), len(kb.rules), len(kb.diagnoses)))
        for w in kb.lint():
            print("  warning: " + w)
        return 0
    if args.demo:
        print("Demo: leaves turning yellow, soil wet, plant kept in low light.\n")
        run_batch(kb, DEMO_ANSWERS)
        return 0
    if args.answers:
        with open(args.answers, "r", encoding="utf-8") as fh:
            run_batch(kb, json.load(fh))
        return 0

    print(rule_line("="))
    print("PLANT DOCTOR - an expert system for common indoor plant problems")
    print(rule_line("="))
    print(wrap("I will ask a few questions about your plant and its conditions, "
               "then suggest the most likely problem and what to do about it. "
               "Only questions that matter for your plant will be asked."))
    print(wrap("Type the number of your answer.  u = don't know, w = why am I being "
               "asked this, b = back, q = quit."))
    while True:
        eng = InferenceEngine(kb)
        if not interview(eng):
            print("Goodbye.")
            return 0
        print()
        print(build_report(eng))
        if after_menu(eng) == "quit":
            print("Goodbye - good luck with your plant!")
            return 0


if __name__ == "__main__":
    sys.exit(main())
