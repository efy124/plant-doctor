"""
engine.py - Rule-based inference engine for the Plant Doctor expert system.

ICT206 Intelligent Systems project - E. Sioras (34792945)

The engine is deliberately small and dependency-free (Python 3.8+ standard
library only) so that it runs on a standard Windows 10 PC without installing
anything.

Main ideas
----------
* Knowledge is stored separately from the code, in knowledge_base.json:
  questions (askable attributes), rules (IF ... THEN ... with a certainty
  factor) and diagnoses (explanations + recommended actions).
* Inference is FORWARD CHAINING over the user's answers. Rules are grouped
  into strata (rules that derive intermediate facts such as
  "excess_moisture" fire before the rules that use them), and the full
  chain is re-run after every answer.  Because the MYCIN combination
  function is commutative and associative, the result does not depend on
  the order in which questions were answered.
* Uncertainty is handled with MYCIN-style CERTAINTY FACTORS (CF) in the range
  -1 (definitely not) .. +1 (definitely).  Rules may carry negative CFs,
  which act as evidence AGAINST a diagnosis.
* The interview is GOAL-DRIVEN: the engine only asks a question if it can
  still affect a rule that might fire ("live" rule) - so the user is not
  asked about pests if they have said they have seen none, for example.
* An EXPLANATION FACILITY records every rule that fired, so the system can
  answer "WHY are you asking this?" and "HOW did you reach that conclusion?".
"""

import json
import os

UNKNOWN = None          # stored when the user answers "don't know"
DIAGNOSIS_ATTR = "diagnosis"


# --------------------------------------------------------------------------
# Certainty-factor arithmetic (Shortliffe & Buchanan, 1975)
# --------------------------------------------------------------------------
def combine_cf(a, b):
    """Combine two certainty factors for the same hypothesis (MYCIN)."""
    if a >= 0 and b >= 0:
        return a + b * (1 - a)
    if a < 0 and b < 0:
        return a + b * (1 + a)
    denom = 1 - min(abs(a), abs(b))
    if denom == 0:          # +1 combined with -1: total contradiction
        return 0.0
    return (a + b) / denom


def confidence_label(cf):
    """Simple heuristic wording for a certainty factor."""
    if cf >= 0.8:
        return "High"
    if cf >= 0.5:
        return "Moderate"
    if cf >= 0.3:
        return "Low"
    return "Very low"


# --------------------------------------------------------------------------
# Knowledge base
# --------------------------------------------------------------------------
class KnowledgeBase(object):
    """Loads and validates the JSON knowledge base."""

    def __init__(self, path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.path = path
        self.meta = data.get("meta", {})
        self.questions = data["questions"]                # ordered dict (py3.7+)
        self.question_order = list(self.questions.keys())
        self.diagnoses = data["diagnoses"]
        self.rules = data["rules"]
        self.rule_by_id = dict((r["id"], r) for r in self.rules)

        th = self.meta.get("thresholds", {})
        self.fire_threshold = th.get("fire", 0.2)
        self.report_threshold = th.get("report", 0.3)
        self.co_threshold = th.get("co_diagnosis", 0.5)

        # attributes that are concluded by rules (not asked)
        self.derived = set(r["then"]["attr"] for r in self.rules)
        self.rules_concluding = {}
        for r in self.rules:
            self.rules_concluding.setdefault(r["then"]["attr"], []).append(r)

        problems = self.validate()
        if problems:
            raise ValueError("Knowledge base errors:\n  " + "\n  ".join(problems))
        self._compute_strata()

    # ---- validation ------------------------------------------------------
    def validate(self):
        """Return a list of structural errors (empty list = OK)."""
        errors = []
        seen = set()
        for r in self.rules:
            if r["id"] in seen:
                errors.append("Duplicate rule id %s" % r["id"])
            seen.add(r["id"])
            if not -1.0 <= r["cf"] <= 1.0:
                errors.append("%s: CF %s outside [-1, 1]" % (r["id"], r["cf"]))
            for cond in r["if"]:
                a = cond["attr"]
                if a in self.questions:
                    opts = self.questions[a]["options"]
                    vals = cond["in"] if "in" in cond else [cond["is"]]
                    for v in vals:
                        if v not in opts:
                            errors.append("%s: '%s' is not an option of %s" % (r["id"], v, a))
                elif a not in self.derived:
                    errors.append("%s: unknown attribute '%s'" % (r["id"], a))
            then = r["then"]
            if then["attr"] in self.questions:
                errors.append("%s concludes an askable attribute %s" % (r["id"], then["attr"]))
            if then["attr"] == DIAGNOSIS_ATTR and then["value"] not in self.diagnoses:
                errors.append("%s: unknown diagnosis '%s'" % (r["id"], then["value"]))
        for q, spec in self.questions.items():
            for cond in spec.get("ask_if", []):
                if cond["attr"] not in self.questions:
                    errors.append("ask_if of %s refers to unknown %s" % (q, cond["attr"]))
        return errors

    def lint(self):
        """Softer quality checks used by the evaluation (warnings, not errors)."""
        warnings = []
        # every diagnosis must be reachable by at least one positive rule
        for d in self.diagnoses:
            pos = [r for r in self.rules_concluding.get(DIAGNOSIS_ATTR, [])
                   if r["then"]["value"] == d and r["cf"] > 0]
            if not pos:
                warnings.append("Diagnosis '%s' has no positive rule" % d)
        # every question should be used by at least one rule
        used = set(c["attr"] for r in self.rules for c in r["if"])
        for spec in self.questions.values():           # gate questions count too
            used.update(g["attr"] for g in spec.get("ask_if", []))
        for q in self.questions:
            if q not in used:
                warnings.append("Question '%s' is never used by a rule" % q)
        # conflicting rules: identical premises, same target, opposite signs
        sig = {}
        for r in self.rules:
            key = (json.dumps(r["if"], sort_keys=True), r["then"]["attr"],
                   str(r["then"]["value"]))
            sig.setdefault(key, []).append(r)
        for key, rs in sig.items():
            if len(rs) > 1:
                signs = set(r["cf"] > 0 for r in rs)
                kind = "Conflicting" if len(signs) > 1 else "Redundant"
                warnings.append("%s rules: %s" % (kind, ", ".join(r["id"] for r in rs)))
        return warnings

    # ---- stratification --------------------------------------------------
    def _compute_strata(self):
        """Depth of each attribute: askable=0, derived = 1 + deepest premise."""
        depth = dict((q, 0) for q in self.questions)

        def attr_depth(attr, visiting):
            if attr in depth:
                return depth[attr]
            if attr in visiting:
                raise ValueError("Cycle in rules involving '%s'" % attr)
            visiting.add(attr)
            d = 0
            for r in self.rules_concluding.get(attr, []):
                for c in r["if"]:
                    d = max(d, attr_depth(c["attr"], visiting))
            visiting.discard(attr)
            depth[attr] = d + 1
            return d + 1

        for a in self.derived:
            attr_depth(a, set())
        self.depth = depth
        self.strata = sorted(set(depth[r["then"]["attr"]] for r in self.rules))

    # ---- helpers -----------------------------------------------------------
    def diagnosis_name(self, key):
        return self.diagnoses[key]["name"]

    def describe_condition(self, cond):
        a = cond["attr"]
        vals = cond["in"] if "in" in cond else [cond["is"]]
        if a in self.questions:
            opts = self.questions[a]["options"]
            text = " or ".join("'%s'" % opts[v] for v in vals)
            return "%s = %s" % (a, text)
        return "%s (derived)" % a


# --------------------------------------------------------------------------
# Inference engine
# --------------------------------------------------------------------------
class InferenceEngine(object):
    """Forward-chaining engine with certainty factors and explanations."""

    def __init__(self, kb):
        self.kb = kb
        self.reset()

    def reset(self):
        self.answers = {}        # askable attr -> value (or UNKNOWN)
        self.history = []        # order in which questions were answered
        self.facts = {}          # derived attr -> {value: cf}
        self.trace = []          # list of fired-rule records (for "how")
        self.fired = set()

    # ---- answers -----------------------------------------------------------
    def set_answer(self, attr, value):
        q = self.kb.questions[attr]
        if value is not UNKNOWN and value in q.get("unknown_values", []):
            value = UNKNOWN
        if value is not UNKNOWN and value not in q["options"]:
            raise ValueError("'%s' is not a valid answer for %s" % (value, attr))
        if attr not in self.answers:
            self.history.append(attr)
        self.answers[attr] = value
        self.infer()

    def undo(self):
        """Remove the most recent answer (for a 'back' command)."""
        if not self.history:
            return None
        attr = self.history.pop()
        del self.answers[attr]
        self.infer()
        return attr

    # ---- premise evaluation ------------------------------------------------
    def condition_cf(self, cond):
        """CF that a single condition holds, or None if not yet known."""
        a = cond["attr"]
        if a in self.kb.questions:
            if a not in self.answers:
                return None
            val = self.answers[a]
            if val is UNKNOWN:
                return 0.0
            ok = val in cond["in"] if "in" in cond else val == cond["is"]
            return 1.0 if ok else 0.0
        # derived fact
        target = cond["in"] if "in" in cond else [cond["is"]]
        best = 0.0
        for v in target:
            best = max(best, self.facts.get(a, {}).get(v, 0.0))
        return best

    def premise_cf(self, rule):
        """min() of condition CFs; None if any askable condition is unasked."""
        cfs = []
        for cond in rule["if"]:
            c = self.condition_cf(cond)
            if c is None:
                return None
            cfs.append(c)
        return min(cfs) if cfs else 1.0

    # ---- forward chaining ---------------------------------------------------
    def infer(self):
        """Re-derive all facts from the current answers (stratified)."""
        self.facts = {}
        self.trace = []
        self.fired = set()
        for stratum in self.kb.strata:
            for rule in self.kb.rules:
                if self.kb.depth[rule["then"]["attr"]] != stratum:
                    continue
                pcf = self.premise_cf(rule)
                if pcf is None or pcf < self.kb.fire_threshold:
                    continue
                attr, val = rule["then"]["attr"], rule["then"]["value"]
                contribution = rule["cf"] * pcf
                old = self.facts.setdefault(attr, {}).get(val)
                new = contribution if old is None else combine_cf(old, contribution)
                self.facts[attr][val] = new
                self.fired.add(rule["id"])
                self.trace.append({
                    "rule": rule["id"], "attr": attr, "value": val,
                    "premise_cf": pcf, "rule_cf": rule["cf"],
                    "contribution": contribution, "before": old, "after": new,
                })
        return self.facts

    # ---- goal-driven question selection ------------------------------------
    def _ask_if_ok(self, attr):
        conds = self.kb.questions[attr].get("ask_if")
        if not conds:
            return True
        for c in conds:
            if c["attr"] in self.answers and self.answers[c["attr"]] is not UNKNOWN:
                if self.answers[c["attr"]] in c["in"]:
                    return True
        return False

    def _could_ask_later(self, attr):
        """False only when every ask_if gate is already closed."""
        conds = self.kb.questions[attr].get("ask_if")
        if not conds:
            return True
        for c in conds:
            g = c["attr"]
            if g not in self.answers:
                return True
            if self.answers[g] is not UNKNOWN and self.answers[g] in c["in"]:
                return True
        return False

    def _derivable(self, attr, visiting=None):
        if self.facts.get(attr):
            if max(self.facts[attr].values()) >= self.kb.fire_threshold:
                return True
        visiting = visiting or set()
        if attr in visiting:
            return False
        visiting.add(attr)
        return any(self.rule_is_live(r, visiting) for r in self.kb.rules_concluding.get(attr, []))

    def rule_is_live(self, rule, visiting=None):
        """A rule is live if it has not fired and could still fire."""
        if rule["id"] in self.fired:
            return False
        for cond in rule["if"]:
            a = cond["attr"]
            if a in self.kb.questions:
                c = self.condition_cf(cond)
                if c is not None and c < self.kb.fire_threshold:
                    return False
                if c is None and not self._could_ask_later(a):
                    return False
            else:
                c = self.condition_cf(cond)
                if c < self.kb.fire_threshold and not self._derivable(a, set(visiting or ())):
                    return False
        return True

    def _rule_worth_asking_for(self, rule):
        """Negative-evidence rules only matter if the target has support."""
        if rule["cf"] >= 0:
            return True
        then = rule["then"]
        return self.facts.get(then["attr"], {}).get(then["value"], 0.0) > 0

    def relevant_rules(self, attr):
        """Live rules that mention attr (used for 'why' and question choice)."""
        out = []
        for r in self.kb.rules:
            if any(c["attr"] == attr for c in r["if"]) and self.rule_is_live(r) \
                    and self._rule_worth_asking_for(r):
                out.append(r)
        return out

    def _is_useful_gate(self, attr):
        """True if answering attr could unlock another still-useful question.

        Example: 'pests_seen' is not used by any rule itself, but a 'yes'
        opens the detailed pest questions (webbing, cottony_white, ...).
        """
        for other in self.kb.question_order:
            if other in self.answers or self._ask_if_ok(other):
                continue
            gates = self.kb.questions[other].get("ask_if", [])
            if any(g["attr"] == attr for g in gates) and self.relevant_rules(other):
                return True
        return False

    def next_question(self):
        """Return the next askable attribute, or None when finished."""
        for attr in self.kb.question_order:
            if attr in self.answers or not self._ask_if_ok(attr):
                continue
            if self.relevant_rules(attr) or self._is_useful_gate(attr):
                return attr
        return None

    # ---- results -------------------------------------------------------------
    def ranked_diagnoses(self, min_cf=None):
        d = self.facts.get(DIAGNOSIS_ATTR, {})
        items = sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))
        if min_cf is not None:
            items = [kv for kv in items if kv[1] >= min_cf]
        return items

    def conclusion(self):
        """Primary diagnosis, co-diagnoses and other possibilities."""
        ranked = self.ranked_diagnoses(self.kb.report_threshold)
        if not ranked:
            return {"primary": None, "co": [], "other": []}
        primary = ranked[0]
        co = [kv for kv in ranked[1:] if kv[1] >= self.kb.co_threshold]
        other = [kv for kv in ranked[1:] if kv[1] < self.kb.co_threshold]
        return {"primary": primary, "co": co, "other": other}

    def explain_how(self, diagnosis):
        """Rules that contributed to a diagnosis (including intermediate facts)."""
        lines = []
        steps = [t for t in self.trace if t["attr"] == DIAGNOSIS_ATTR and t["value"] == diagnosis]
        needed = set()
        for t in steps:
            for c in self.kb.rule_by_id[t["rule"]]["if"]:
                if c["attr"] in self.kb.derived:
                    needed.add(c["attr"])
        for t in self.trace:
            if t["attr"] in needed:
                lines.append(self._format_step(t))
        for t in steps:
            lines.append(self._format_step(t))
        return lines

    def _format_step(self, t):
        r = self.kb.rule_by_id[t["rule"]]
        conds = " AND ".join(self._cond_short(c) for c in r["if"])
        concl = t["value"] if t["attr"] == DIAGNOSIS_ATTR else t["attr"]
        sign = "supports" if t["contribution"] >= 0 else "argues AGAINST"
        return ("%s: IF %s THEN %s (rule CF %+.2f) -> %s, CF now %.2f.  [%s] %s" %
                (t["rule"], conds, concl, r["cf"], sign, t["after"],
                 r.get("source", ""), r.get("note", "")))

    def _cond_short(self, c):
        vals = c["in"] if "in" in c else [c["is"]]
        if c["attr"] in self.kb.questions:
            return "%s=%s" % (c["attr"], "/".join(str(v) for v in vals))
        return c["attr"]


def load_default_kb():
    here = os.path.dirname(os.path.abspath(__file__))
    return KnowledgeBase(os.path.join(here, "knowledge_base.json"))


def diagnose(kb, answers):
    """Non-interactive consultation used by the evaluation harness.

    `answers` maps attribute -> value for everything the 'user' knows.
    The engine still runs its normal goal-driven interview, so only the
    questions it actually asks are counted.  Returns (engine, asked_list).
    """
    eng = InferenceEngine(kb)
    asked = []
    while True:
        q = eng.next_question()
        if q is None:
            break
        asked.append(q)
        eng.set_answer(q, answers.get(q, UNKNOWN))
    return eng, asked
