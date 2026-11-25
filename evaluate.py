"""
evaluate.py - Evaluation harness for the Plant Doctor expert system.

ICT206 Intelligent Systems project - E. Sioras

Usage
    python evaluate.py               evaluate on the held-out TEST set
    python evaluate.py --set dev     evaluate on the development set
    python evaluate.py --no-charts   skip charts (no matplotlib needed)

What it measures
    1. Accuracy  = correct primary diagnoses / total cases x 100  (target >= 80%)
       plus lenient accuracy (co-diagnosis accepted), top-3 accuracy and
       detection of BOTH problems in multi-problem cases.
    2. Comparison with two baselines that use the same knowledge without
       inference: a majority-class guess and a flat symptom-checklist matcher.
    3. Rule coverage - every rule fires in at least one case - and
       knowledge-base consistency checks (conflicting / redundant rules).
    4. Order independence - answers given in 50 random orders must always
       produce identical conclusions.
    5. Robustness - accuracy as a growing share of answers become "don't know".
    6. Interview efficiency - number of questions actually asked.

Outputs are written to the results/ folder (CSV, text summary, PNG charts).
"""

import argparse
import csv
import json
import os
import random
import sys
from collections import Counter, OrderedDict

from engine import DIAGNOSIS_ATTR, UNKNOWN, InferenceEngine, KnowledgeBase, diagnose

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def load_cases(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def full_answers(defaults, case):
    a = dict(defaults)
    a.update(case["answers"])
    return dict((k, UNKNOWN if v == "unknown" else v) for k, v in a.items())


def predict(kb, answers):
    eng, asked = diagnose(kb, answers)
    res = eng.conclusion()
    primary = res["primary"][0] if res["primary"] else "none"
    cf = res["primary"][1] if res["primary"] else 0.0
    predicted_set = [primary] + [k for k, _ in res["co"]] if res["primary"] else []
    ranked = [k for k, _ in eng.ranked_diagnoses(kb.report_threshold)]
    return {"primary": primary, "cf": cf, "set": predicted_set, "top3": ranked[:3],
            "asked": asked, "engine": eng}


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------
class FlatChecklistBaseline(object):
    """Static symptom checklist built from the SAME knowledge base.

    For each diagnosis it collects every (question, answer) pair that appears
    in a positive rule for it (intermediate facts are expanded one level).
    A case is scored by the fraction of a diagnosis' checklist it matches -
    like a printed troubleshooting table.  It has no chaining, no certainty
    factors, no negative evidence and no thresholds.
    """

    def __init__(self, kb):
        self.kb = kb
        self.profile = {}
        for r in kb.rules:
            if r["then"]["attr"] != DIAGNOSIS_ATTR or r["cf"] <= 0:
                continue
            items = self.profile.setdefault(r["then"]["value"], set())
            for c in r["if"]:
                for item in self._expand(c):
                    items.add(item)

    def _expand(self, cond):
        a = cond["attr"]
        if a in self.kb.questions:
            vals = cond["in"] if "in" in cond else [cond["is"]]
            return [(a, v) for v in vals]
        out = []
        for r in self.kb.rules_concluding.get(a, []):
            if r["cf"] > 0:
                for c in r["if"]:
                    if c["attr"] in self.kb.questions:
                        vals = c["in"] if "in" in c else [c["is"]]
                        out.extend((c["attr"], v) for v in vals)
        return out

    def predict(self, answers):
        best, best_score = "none", (0.0, 0)
        for d in sorted(self.profile):
            items = self.profile[d]
            hits = sum(1 for (a, v) in items if answers.get(a) == v)
            score = (hits / float(len(items)), hits)
            if score > best_score:
                best, best_score = d, score
        return best


# --------------------------------------------------------------------------
# Evaluation steps
# --------------------------------------------------------------------------
def evaluate_cases(kb, data, cases):
    baseline = FlatChecklistBaseline(kb)
    majority = Counter(c["expected"] for c in cases).most_common(1)[0][0]
    rows = []
    for c in cases:
        ans = full_answers(data["defaults"], c)
        p = predict(kb, ans)
        ok_set = [c["expected"]] + c.get("acceptable", [])
        required = [c["expected"]] + c.get("also_required", [])
        rows.append(OrderedDict([
            ("id", c["id"]), ("type", c["type"]), ("expected", c["expected"]),
            ("predicted", p["primary"]), ("cf", round(p["cf"], 3)),
            ("co_diagnoses", ";".join(p["set"][1:])),
            ("correct", int(p["primary"] == c["expected"])),
            ("correct_lenient", int(p["primary"] in ok_set)),
            ("in_top3", int(c["expected"] in p["top3"] or
                            (c["expected"] == "none" and p["primary"] == "none"))),
            ("all_required_found", int(all(r in p["set"] for r in required))
             if c["type"] == "multi" else ""),
            ("questions_asked", len(p["asked"])),
            ("baseline_checklist", baseline.predict(ans)),
            ("baseline_majority", majority),
            ("rules_fired", " ".join(sorted(p["engine"].fired,
                                            key=lambda x: int(x[1:])))),
        ]))
    return rows, majority


def rule_coverage(kb, data):
    fired = set()
    for c in data["dev"] + data["test"]:
        _, _ = None, None
        p = predict(kb, full_answers(data["defaults"], c))
        fired |= p["engine"].fired
    never = [r["id"] for r in kb.rules if r["id"] not in fired]
    return len(fired), len(kb.rules), never


def _same_facts(f1, f2):
    if set(f1) != set(f2):
        return False
    for attr in f1:
        a, b = f1[attr], f2[attr]
        if set(a) != set(b) or any(abs(a[k] - b[k]) > 1e-9 for k in a):
            return False
    return True


def _conclusion_key(eng):
    res = eng.conclusion()
    if not res["primary"]:
        return ("none",)
    items = [res["primary"]] + res["co"] + res["other"]
    return tuple((k, round(v, 6)) for k, v in items)


def order_independence(kb, data, cases, trials=50, seed=206):
    """(a) Answer ALL facts in random orders - every derived fact and CF must
    be identical.  (b) The goal-driven interview (which skips questions) must
    reach exactly the same reported conclusion as answering everything."""
    rng = random.Random(seed)
    failures = checks = 0
    pruning_same = 0
    for c in cases:
        ans = full_answers(data["defaults"], c)
        canon = InferenceEngine(kb)
        for k in ans:
            canon.set_answer(k, ans[k])
        for _ in range(trials):
            keys = list(ans.keys())
            rng.shuffle(keys)
            eng = InferenceEngine(kb)
            for k in keys:
                eng.set_answer(k, ans[k])
            checks += 1
            if not _same_facts(eng.facts, canon.facts):
                failures += 1
        interviewed = predict(kb, ans)["engine"]
        pruning_same += int(_conclusion_key(interviewed) == _conclusion_key(canon))
    return checks, failures, pruning_same


def robustness(kb, data, cases, levels=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
               trials=30, seed=305):
    """Accuracy when a random share of the user's answers become 'don't know'."""
    rng = random.Random(seed)
    baseline = FlatChecklistBaseline(kb)
    out = []
    for p in levels:
        sys_ok = base_ok = total = abstain = sys_wrong = base_wrong = 0
        for _ in range(trials):
            for c in cases:
                ans = full_answers(data["defaults"], c)
                for k in list(ans.keys()):
                    if rng.random() < p:
                        ans[k] = UNKNOWN
                total += 1
                got = predict(kb, ans)["primary"]
                b = baseline.predict(ans)
                sys_ok += int(got == c["expected"])
                base_ok += int(b == c["expected"])
                if got != c["expected"]:
                    if got == "none":
                        abstain += 1
                    else:
                        sys_wrong += 1
                if b != c["expected"]:
                    base_wrong += 1
        out.append((p, 100.0 * sys_ok / total, 100.0 * base_ok / total,
                    100.0 * abstain / total, 100.0 * sys_wrong / total,
                    100.0 * base_wrong / total))
    return out


# --------------------------------------------------------------------------
# Charts (optional - need matplotlib)
# --------------------------------------------------------------------------
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GREY, INK, INK2, GRID = "#a3a29c", "#0b0b0b", "#52514e", "#e6e5e0"


def make_charts(summary, rows, robust, label_names, outdir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed - charts skipped (pip install matplotlib)")
        return []
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
        "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.dpi": 200, "savefig.bbox": "tight", "savefig.facecolor": "white",
    })
    files = []

    # 1. accuracy comparison --------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    labels = ["Majority-class\nbaseline", "Flat checklist\nbaseline",
              "Plant Doctor\n(strict)", "Plant Doctor\n(lenient)"]
    vals = [summary["acc_majority"], summary["acc_checklist"],
            summary["acc_strict"], summary["acc_lenient"]]
    colours = [GREY, GREY, BLUE, BLUE]
    bars = ax.bar(labels, vals, color=colours, width=0.55, zorder=3)
    ax.axhline(80, color=ORANGE, lw=1.5, ls="--", zorder=4)
    ax.text(-0.42, 81.5, "80% target", color=INK2, ha="left", va="bottom", fontsize=9)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.5, "%.1f%%" % v,
                ha="center", va="bottom", color=INK, fontsize=9)
    ax.set_ylim(0, 108)
    ax.set_ylabel("Primary-diagnosis accuracy (%)")
    ax.yaxis.grid(True, color=GRID, lw=0.8, zorder=0)
    ax.tick_params(axis="x", length=0)
    f = os.path.join(outdir, "fig1_accuracy.png")
    fig.savefig(f)
    plt.close(fig)
    files.append(f)

    # 2. robustness --------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    xs = [100 * r[0] for r in robust]
    series = [
        ("Plant Doctor - correct", [r[1] for r in robust], BLUE, "-", "o"),
        ("Checklist - correct", [r[2] for r in robust], GREY, "-", "s"),
        ("Checklist - wrong", [r[5] for r in robust], GREY, "--", "s"),
        ("Plant Doctor - wrong", [r[4] for r in robust], BLUE, "--", "o"),
    ]
    for name, ys, col, ls, mk in series:
        ax.plot(xs, ys, color=col, lw=2, ls=ls, marker=mk, ms=5, zorder=3, label=name)
    # direct labels at the right end, nudged apart so they never collide
    ends = sorted(((s[1][-1], s[0]) for s in series))
    placed = []
    for y, name in ends:
        while placed and y - placed[-1] < 6:
            y = placed[-1] + 6
        placed.append(y)
        ax.text(xs[-1] + 1.5, y, name, color=INK, va="center", fontsize=8)
    ax.set_xlim(-2, xs[-1] + 22)
    ax.set_ylim(0, 105)
    ax.set_xlabel("Answers replaced by \"don't know\" (%)")
    ax.set_ylabel("Share of cases (%)")
    ax.set_xticks(xs)
    ax.yaxis.grid(True, color=GRID, lw=0.8, zorder=0)
    f = os.path.join(outdir, "fig2_robustness.png")
    fig.savefig(f)
    plt.close(fig)
    files.append(f)

    # 3. confusion matrix -------------------------------------------------
    import matplotlib.colors as mcolors
    classes = sorted(set(r["expected"] for r in rows) | set(r["predicted"] for r in rows),
                     key=lambda k: (k == "none", k))
    idx = dict((k, i) for i, k in enumerate(classes))
    m = [[0] * len(classes) for _ in classes]
    for r in rows:
        m[idx[r["expected"]]][idx[r["predicted"]]] += 1
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "seqblue", ["#ffffff", "#cde2fb", "#86b6ef", "#2a78d6", "#184f95"])
    fig, ax = plt.subplots(figsize=(6.4, 5.6))
    ax.imshow(m, cmap=cmap, vmin=0, vmax=max(max(row) for row in m))
    names = [label_names.get(k, k) for k in classes]
    ax.set_xticks(range(len(classes)))
    ax.set_yticks(range(len(classes)))
    ax.set_xticklabels(names, rotation=50, ha="right", fontsize=8)
    ax.set_yticklabels(names, fontsize=8)
    for i in range(len(classes)):
        for j in range(len(classes)):
            if m[i][j]:
                ax.text(j, i, str(m[i][j]), ha="center", va="center", fontsize=8,
                        color="white" if m[i][j] >= 3 else INK)
    ax.set_xticks([x - 0.5 for x in range(1, len(classes))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(classes))], minor=True)
    ax.grid(which="minor", color=GRID, lw=0.6)
    ax.tick_params(which="both", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xlabel("Predicted (primary diagnosis)")
    ax.set_ylabel("Expected")
    f = os.path.join(outdir, "fig3_confusion.png")
    fig.savefig(f)
    plt.close(fig)
    files.append(f)

    # 4. questions asked ---------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    ids = [r["id"] for r in rows]
    q = [r["questions_asked"] for r in rows]
    cols = [BLUE if r["correct"] else ORANGE for r in rows]
    ax.bar(ids, q, color=cols, width=0.7, zorder=3)
    ax.axhline(summary["n_questions"], color=GREY, lw=1.2, ls=":", zorder=2)
    ax.text(len(ids) - 0.5, summary["n_questions"] + 0.4,
            "all %d questions" % summary["n_questions"], ha="right", va="bottom",
            color=INK2, fontsize=8)
    ax.set_ylim(0, summary["n_questions"] + 4)
    ax.set_ylabel("Questions asked")
    ax.tick_params(axis="x", rotation=90, labelsize=7, length=0)
    ax.yaxis.grid(True, color=GRID, lw=0.8, zorder=0)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=BLUE, label="correct"), Patch(color=ORANGE, label="incorrect")],
              frameon=False, fontsize=8, loc="upper left", ncol=2)
    f = os.path.join(outdir, "fig4_questions.png")
    fig.savefig(f)
    plt.close(fig)
    files.append(f)
    return files


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def pct(n, d):
    return 100.0 * n / d if d else 0.0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate the Plant Doctor expert system")
    ap.add_argument("--set", choices=["test", "dev"], default="test")
    ap.add_argument("--cases", default=os.path.join(HERE, "test_cases.json"))
    ap.add_argument("--kb", default=os.path.join(HERE, "knowledge_base.json"))
    ap.add_argument("--no-charts", action="store_true")
    args = ap.parse_args(argv)

    kb = KnowledgeBase(args.kb)
    data = load_cases(args.cases)
    cases = data[args.set]
    if not os.path.isdir(RESULTS):
        os.makedirs(RESULTS)

    rows, majority = evaluate_cases(kb, data, cases)
    n = len(rows)
    multi = [r for r in rows if r["type"] == "multi"]
    summary = OrderedDict([
        ("set", args.set), ("cases", n),
        ("acc_strict", pct(sum(r["correct"] for r in rows), n)),
        ("acc_lenient", pct(sum(r["correct_lenient"] for r in rows), n)),
        ("acc_top3", pct(sum(r["in_top3"] for r in rows), n)),
        ("multi_both_found", "%d/%d" % (sum(r["all_required_found"] for r in multi), len(multi))),
        ("acc_checklist", pct(sum(r["baseline_checklist"] == r["expected"] for r in rows), n)),
        ("acc_majority", pct(sum(r["baseline_majority"] == r["expected"] for r in rows), n)),
        ("majority_class", majority),
        ("mean_questions", sum(r["questions_asked"] for r in rows) / float(n)),
        ("min_questions", min(r["questions_asked"] for r in rows)),
        ("max_questions", max(r["questions_asked"] for r in rows)),
        ("n_questions", len(kb.questions)),
        ("mean_cf_correct", sum(r["cf"] for r in rows if r["correct"]) /
         max(1, sum(r["correct"] for r in rows))),
        ("mean_cf_incorrect", sum(r["cf"] for r in rows if not r["correct"]) /
         max(1, sum(1 - r["correct"] for r in rows))),
    ])
    by_type = OrderedDict()
    for r in rows:
        t = by_type.setdefault(r["type"], [0, 0])
        t[0] += r["correct"]
        t[1] += 1

    fired, total_rules, never = rule_coverage(kb, data)
    checks, failures, pruning_same = order_independence(kb, data, cases)
    robust = robustness(kb, data, cases)
    lint = kb.lint()

    # ---- write CSV --------------------------------------------------------
    csv_path = os.path.join(RESULTS, "%s_results.csv" % args.set)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(RESULTS, "%s_robustness.csv" % args.set), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["share_unknown", "plant_doctor_correct", "checklist_correct",
                    "plant_doctor_abstained", "plant_doctor_wrong", "checklist_wrong"])
        for row in robust:
            w.writerow([row[0]] + [round(x, 2) for x in row[1:]])

    # ---- text summary -------------------------------------------------------
    L = []
    L.append("PLANT DOCTOR - EVALUATION SUMMARY (%s set, %d cases)" % (args.set.upper(), n))
    L.append("=" * 70)
    L.append("Knowledge base: %d questions, %d rules, %d diagnoses" %
             (len(kb.questions), len(kb.rules), len(kb.diagnoses)))
    L.append("")
    L.append("1. ACCURACY")
    L.append("   Primary diagnosis correct (strict) : %5.1f%%   (target >= 80%%)" % summary["acc_strict"])
    L.append("   Correct incl. acceptable co-diag.  : %5.1f%%" % summary["acc_lenient"])
    L.append("   Expected diagnosis in top 3        : %5.1f%%" % summary["acc_top3"])
    L.append("   Multi-problem cases, both found    : %s" % summary["multi_both_found"])
    L.append("   Accuracy by case type:")
    for t, (ok, tot) in by_type.items():
        L.append("     %-8s %2d/%-2d  (%.0f%%)" % (t, ok, tot, pct(ok, tot)))
    L.append("   Mean CF when correct / incorrect   : %.2f / %.2f" %
             (summary["mean_cf_correct"], summary["mean_cf_incorrect"]))
    L.append("")
    L.append("2. BASELINES")
    L.append("   Majority class ('%s')       : %5.1f%%" % (majority, summary["acc_majority"]))
    L.append("   Flat symptom checklist             : %5.1f%%" % summary["acc_checklist"])
    L.append("")
    L.append("3. RULE COVERAGE AND CONSISTENCY (dev + test cases)")
    L.append("   Rules fired at least once          : %d/%d (%.0f%%)" %
             (fired, total_rules, pct(fired, total_rules)))
    L.append("   Rules never fired                  : %s" % (", ".join(never) or "none"))
    L.append("   KB lint warnings                   : %s" % ("; ".join(lint) or "none"))
    L.append("")
    L.append("4. ORDER INDEPENDENCE AND INTERVIEW PRUNING")
    L.append("   %d random answer orders, %d gave different facts or CFs" % (checks, failures))
    L.append("   Interview reached the same conclusion as answering all")
    L.append("   %d questions in %d/%d cases" % (len(kb.questions), pruning_same, n))
    L.append("")
    L.append("5. ROBUSTNESS (30 random trials per level)")
    L.append("              ---- Plant Doctor ----------------   - Checklist -")
    L.append("   unknown   correct  abstained  wrong diagnosis   correct  wrong")
    for p, s, b, ab, sw, bw in robust:
        L.append("   %5.0f%%    %6.1f%%    %6.1f%%       %6.1f%%     %6.1f%%  %5.1f%%"
                 % (100 * p, s, ab, sw, b, bw))
    L.append("")
    L.append("6. INTERVIEW EFFICIENCY")
    L.append("   Questions asked: mean %.1f (min %d, max %d) of %d available" %
             (summary["mean_questions"], summary["min_questions"],
              summary["max_questions"], summary["n_questions"]))
    L.append("")
    L.append("7. INCORRECT CASES")
    wrong = [r for r in rows if not r["correct"]]
    if not wrong:
        L.append("   none")
    for r in wrong:
        L.append("   %s (%s): expected %s, got %s (CF %.2f)%s" %
                 (r["id"], r["type"], r["expected"], r["predicted"], r["cf"],
                  "  [acceptable]" if r["correct_lenient"] else ""))
    L.append("")
    L.append("Per-case results: %s" % os.path.relpath(csv_path, HERE))
    text = "\n".join(L)
    print(text)
    with open(os.path.join(RESULTS, "%s_summary.txt" % args.set), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    with open(os.path.join(RESULTS, "%s_summary.json" % args.set), "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "by_type": by_type, "rules_fired": fired,
                   "rules_total": total_rules, "never_fired": never,
                   "order_checks": checks, "order_failures": failures,
                   "pruning_same": pruning_same,
                   "robustness": robust, "lint": lint}, fh, indent=2)

    if not args.no_charts:
        names = dict((k, v["name"].split(" (")[0].split(" /")[0])
                     for k, v in kb.diagnoses.items())
        names["none"] = "No diagnosis"
        names["cold_draft_stress"] = "Cold / draught"
        sub = os.path.join(RESULTS, "charts_%s" % args.set)
        if not os.path.isdir(sub):
            os.makedirs(sub)
        for f in make_charts(summary, rows, robust, names, sub):
            print("chart: %s" % os.path.relpath(f, HERE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
