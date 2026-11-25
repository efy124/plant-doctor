"""
gui.py - Graphical user interface for the Plant Doctor expert system.

ICT206 Intelligent Systems project - E. Sioras (34792945)

Usage
    python gui.py          (or double-click run_gui.bat on Windows)

Uses only Tkinter, which ships with the standard Windows Python installer,
so nothing extra has to be installed.  The GUI is a thin layer over the same
InferenceEngine and knowledge_base.json used by the command-line version
(plant_doctor.py) and the evaluation (evaluate.py), so its conclusions are
identical to those reported in the evaluation.

Keyboard shortcuts while answering:  1-9 choose an option,  U = don't know,
B = back,  W = why is this question asked.
"""

import os
import sys
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox

from engine import KnowledgeBase, InferenceEngine, UNKNOWN, confidence_label
from plant_doctor import build_report, answers_summary

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- palette
BG = "#f4f3ef"          # window background
CARD = "#ffffff"        # card background
INK = "#1d1d1b"         # primary text
INK2 = "#5b5a55"        # secondary text
MUTED = "#8a8983"       # muted text
LINE = "#e2e0d9"        # borders
ACCENT = "#2f7d4f"      # plant green
ACCENT_DARK = "#235f3c"
ACCENT_LIGHT = "#e6f2ea"
HOVER = "#f0f6f2"
BAR_BG = "#ecebe6"
WARN = "#b5541c"


def pick_font_family(root):
    available = set(tkfont.families(root))
    for fam in ("Segoe UI", "Helvetica Neue", "Inter", "DejaVu Sans", "Arial"):
        if fam in available:
            return fam
    return "TkDefaultFont"


class PlantDoctorGUI(object):
    def __init__(self, root, kb):
        self.root = root
        self.kb = kb
        self.engine = InferenceEngine(kb)
        self.current_attr = None
        self.option_keys = []
        fam = pick_font_family(root)
        self.f_title = (fam, 17, "bold")
        self.f_sub = (fam, 10)
        self.f_q = (fam, 14, "bold")
        self.f_body = (fam, 10)
        self.f_small = (fam, 9)
        self.f_opt = (fam, 11)
        self.f_head = (fam, 11, "bold")
        self.f_big = (fam, 16, "bold")

        root.title("Plant Doctor - indoor plant problem expert system")
        root.configure(bg=BG)
        root.geometry("1060x700")
        root.minsize(900, 600)

        self._build_header()
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        self.left = tk.Frame(body, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.right = tk.Frame(body, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        self.right.grid(row=0, column=1, sticky="nsew")
        self._build_side_panel()

        root.bind("<Key>", self._on_key)
        self.show_question()

    # ------------------------------------------------------------ layout
    def _build_header(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=16, pady=(14, 10))
        logo = tk.Canvas(bar, width=34, height=34, bg=BG, highlightthickness=0)
        logo.create_oval(2, 2, 32, 32, fill=ACCENT, outline="")
        logo.create_polygon(17, 9, 25, 15, 17, 26, 9, 15, fill="white", outline="", smooth=True)
        logo.create_line(17, 13, 17, 26, fill=ACCENT, width=1.5)
        logo.pack(side="left", padx=(0, 10))
        titles = tk.Frame(bar, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text="Plant Doctor", font=self.f_title, bg=BG, fg=INK).pack(anchor="w")
        tk.Label(titles, text="Expert system for common indoor plant problems",
                 font=self.f_sub, bg=BG, fg=INK2).pack(anchor="w")
        self.btn_restart = self._button(bar, "New plant", self.restart, primary=False)
        self.btn_restart.pack(side="right")

    def _build_side_panel(self):
        p = self.right
        tk.Label(p, text="Current evidence", font=self.f_head, bg=CARD, fg=INK).pack(
            anchor="w", padx=18, pady=(16, 0))
        tk.Label(p, text="Leading diagnoses and their certainty factor (CF), "
                         "updated after every answer.", font=self.f_small, bg=CARD,
                 fg=INK2, wraplength=340, justify="left").pack(anchor="w", padx=18, pady=(2, 8))
        self.bars = tk.Canvas(p, bg=CARD, height=230, highlightthickness=0)
        self.bars.pack(fill="x", padx=18)
        self.bars.bind("<Configure>", lambda e: self.update_side())
        tk.Frame(p, bg=LINE, height=1).pack(fill="x", padx=18, pady=(8, 10))
        tk.Label(p, text="Your answers", font=self.f_head, bg=CARD, fg=INK).pack(anchor="w", padx=18)
        frame = tk.Frame(p, bg=CARD)
        frame.pack(fill="both", expand=True, padx=18, pady=(6, 16))
        self.answers_box = tk.Text(frame, font=self.f_small, bg=CARD, fg=INK2, relief="flat",
                                   wrap="word", height=8, cursor="arrow",
                                   highlightthickness=0, borderwidth=0)
        sb = tk.Scrollbar(frame, command=self.answers_box.yview)
        self.answers_box.configure(yscrollcommand=sb.set, state="disabled")
        self.answers_box.tag_configure("attr", foreground=MUTED)
        self.answers_box.tag_configure("val", foreground=INK)
        sb.pack(side="right", fill="y")
        self.answers_box.pack(side="left", fill="both", expand=True)

    def _button(self, parent, text, command, primary=True, width=None):
        bg, fg, act = (ACCENT, "white", ACCENT_DARK) if primary else (CARD, INK, HOVER)
        b = tk.Button(parent, text=text, command=command, font=self.f_body, bg=bg, fg=fg,
                      activebackground=act, activeforeground=fg, relief="flat", cursor="hand2",
                      padx=14, pady=6, borderwidth=0, highlightthickness=1,
                      highlightbackground=ACCENT if primary else LINE)
        if width:
            b.configure(width=width)
        return b

    def _clear_left(self):
        for w in self.left.winfo_children():
            w.destroy()

    # ------------------------------------------------------------ question screen
    def show_question(self):
        self.update_side()
        attr = self.engine.next_question()
        if attr is None:
            self.show_results()
            return
        self.current_attr = attr
        q = self.kb.questions[attr]
        self._clear_left()
        wrap = 560
        top = tk.Frame(self.left, bg=CARD)
        top.pack(fill="x", padx=24, pady=(20, 0))
        n = len(self.engine.history) + 1
        tk.Label(top, text="QUESTION %d" % n, font=(self.f_small[0], 9, "bold"),
                 bg=CARD, fg=ACCENT).pack(side="left")
        tk.Label(top, text="Only questions that can still change the result are asked",
                 font=self.f_small, bg=CARD, fg=MUTED).pack(side="right")
        tk.Label(self.left, text=q["text"], font=self.f_q, bg=CARD, fg=INK, wraplength=wrap,
                 justify="left").pack(anchor="w", padx=24, pady=(8, 2))
        if q.get("help"):
            tk.Label(self.left, text=q["help"], font=self.f_small, bg=CARD, fg=INK2,
                     wraplength=wrap, justify="left").pack(anchor="w", padx=24, pady=(0, 4))

        opts = tk.Frame(self.left, bg=CARD)
        opts.pack(fill="x", padx=24, pady=(10, 0))
        self.option_keys = list(q["options"].keys())
        for i, key in enumerate(self.option_keys, 1):
            self._option_row(opts, i, q["options"][key], key)

        nav = tk.Frame(self.left, bg=CARD)
        nav.pack(fill="x", side="bottom", padx=24, pady=20)
        self._button(nav, "Don't know (U)", lambda: self.answer(UNKNOWN), primary=False).pack(side="left")
        self._button(nav, "Why this question? (W)", self.show_why, primary=False).pack(side="left", padx=8)
        back = self._button(nav, "Back (B)", self.back, primary=False)
        back.pack(side="right")
        if not self.engine.history:
            back.configure(state="disabled", cursor="arrow")

    def _option_row(self, parent, num, text, key):
        row = tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1, cursor="hand2")
        row.pack(fill="x", pady=4)
        badge = tk.Label(row, text=str(num), font=(self.f_opt[0], 10, "bold"), bg=ACCENT_LIGHT,
                         fg=ACCENT_DARK, width=3, pady=6)
        badge.pack(side="left", padx=(8, 10), pady=6)
        lab = tk.Label(row, text=text, font=self.f_opt, bg=CARD, fg=INK, anchor="w",
                       justify="left", wraplength=480)
        lab.pack(side="left", fill="x", expand=True, pady=6)

        def enter(_e):
            for w in (row, lab):
                w.configure(bg=HOVER)
            row.configure(highlightbackground=ACCENT)

        def leave(_e):
            for w in (row, lab):
                w.configure(bg=CARD)
            row.configure(highlightbackground=LINE)

        for w in (row, badge, lab):
            w.bind("<Button-1>", lambda _e, k=key: self.answer(k))
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    # ------------------------------------------------------------ actions
    def answer(self, value):
        if self.current_attr is None:
            return
        self.engine.set_answer(self.current_attr, value)
        self.show_question()

    def back(self):
        if self.engine.history:
            self.engine.undo()
            self.show_question()

    def restart(self):
        self.engine = InferenceEngine(self.kb)
        self.current_attr = None
        self.show_question()

    def _on_key(self, event):
        if self.current_attr is None:
            return
        ch = (event.char or "").lower()
        if ch.isdigit() and 1 <= int(ch) <= len(self.option_keys):
            self.answer(self.option_keys[int(ch) - 1])
        elif ch == "u":
            self.answer(UNKNOWN)
        elif ch == "b":
            self.back()
        elif ch == "w":
            self.show_why()

    def show_why(self):
        attr = self.current_attr
        if attr is None:
            return
        lines = []
        for r in self.engine.relevant_rules(attr):
            then = r["then"]
            if then["attr"] == "diagnosis":
                target = self.kb.diagnosis_name(then["value"])
            else:
                target = "intermediate fact '%s'" % then["attr"]
            direction = "evidence FOR" if r["cf"] > 0 else "evidence AGAINST"
            lines.append((r["id"], target, direction, r.get("note", ""), r.get("source", "")))
        if not lines:   # a gate question
            lines.append(("-", "follow-up questions", "unlocks",
                          "Your answer decides whether the detailed questions are needed.", ""))
        self._text_window("Why am I asked this?",
                          "This question can confirm or rule out:",
                          [("%s  -  %s (%s, rule %s)" % (t, n, d, i), s) for i, t, d, n, s in lines])

    # ------------------------------------------------------------ side panel
    def update_side(self):
        c = self.bars
        c.delete("all")
        w = max(c.winfo_width(), 300)
        ranked = [kv for kv in self.engine.ranked_diagnoses() if kv[1] > 0][:6]
        if not ranked:
            c.create_text(0, 18, anchor="w", text="No evidence yet - answer a few questions.",
                          font=self.f_small, fill=MUTED)
        y = 6
        for key, cf in ranked:
            name = self.kb.diagnosis_name(key).split(" (")[0].split(" /")[0]
            c.create_text(0, y + 7, anchor="w", text=name, font=self.f_body, fill=INK)
            c.create_text(w, y + 7, anchor="e", text="%.2f  %s" % (cf, confidence_label(cf)),
                          font=self.f_small, fill=INK2)
            c.create_rectangle(0, y + 18, w, y + 26, fill=BAR_BG, outline="")
            colour = ACCENT if cf >= self.kb.report_threshold else "#9bbfa8"
            c.create_rectangle(0, y + 18, max(3, w * cf), y + 26, fill=colour, outline="")
            y += 37
        # threshold marker
        if ranked:
            x = w * self.kb.report_threshold
            c.create_line(x, 2, x, y - 8, fill=MUTED, dash=(2, 3))
        c.configure(height=max(40, y))

        box = self.answers_box
        box.configure(state="normal")
        box.delete("1.0", "end")
        for attr in self.engine.history:
            v = self.engine.answers[attr]
            txt = "don't know" if v is UNKNOWN else self.kb.questions[attr]["options"][v]
            box.insert("end", attr.replace("_", " ") + ": ", "attr")
            box.insert("end", txt + "\n", "val")
        box.see("end")
        box.configure(state="disabled")

    # ------------------------------------------------------------ results
    def show_results(self):
        self.current_attr = None
        self._clear_left()
        res = self.engine.conclusion()

        nav = tk.Frame(self.left, bg=CARD)
        nav.pack(fill="x", side="bottom", padx=24, pady=16)
        self._button(nav, "How did you decide?", self.show_how).pack(side="left")
        self._button(nav, "Save report...", self.save_report, primary=False).pack(side="left", padx=8)
        self._button(nav, "Back", self.back, primary=False).pack(side="right")

        frame = tk.Frame(self.left, bg=CARD)
        frame.pack(fill="both", expand=True, padx=(24, 8), pady=(18, 0))
        t = tk.Text(frame, font=self.f_body, bg=CARD, fg=INK, relief="flat", wrap="word",
                    highlightthickness=0, borderwidth=0, padx=0, cursor="arrow", spacing1=1, spacing3=2)
        sb = tk.Scrollbar(frame, command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        t.tag_configure("kicker", font=(self.f_small[0], 9, "bold"), foreground=ACCENT, spacing1=4)
        t.tag_configure("title", font=self.f_big, foreground=INK, spacing1=2, spacing3=2)
        t.tag_configure("title2", font=self.f_q, foreground=INK, spacing1=2)
        t.tag_configure("conf", font=self.f_small, foreground=INK2, spacing3=6)
        t.tag_configure("head", font=self.f_head, foreground=INK, spacing1=8, spacing3=2)
        t.tag_configure("body", font=self.f_body, foreground=INK, lmargin1=0, lmargin2=0)
        t.tag_configure("bullet", font=self.f_body, foreground=INK, lmargin1=8, lmargin2=22)
        t.tag_configure("muted", font=self.f_small, foreground=INK2)
        t.tag_configure("warn", font=self.f_body, foreground=WARN)

        if res["primary"] is None:
            t.insert("end", "NO CONFIDENT DIAGNOSIS\n", "kicker")
            t.insert("end", "I couldn't reach a confident diagnosis\n", "title")
            t.insert("end", "Check the roots and the undersides of leaves, then try again - or take a "
                            "photo and a leaf sample to a local nursery.\n", "body")
            weak = [kv for kv in self.engine.ranked_diagnoses() if kv[1] > 0.1][:3]
            if weak:
                t.insert("end", "Weak leads worth checking\n", "head")
                for key, cf in weak:
                    t.insert("end", "•  %s (CF %.2f)\n" % (self.kb.diagnosis_name(key), cf), "bullet")
        else:
            self._diag_block(t, res["primary"], "MOST LIKELY PROBLEM", "title")
            for item in res["co"]:
                t.insert("end", "\n")
                self._diag_block(t, item, "ALSO LIKELY - COMBINED PROBLEM", "title2")
            if res["other"]:
                t.insert("end", "Other possibilities (low confidence)\n", "head")
                for key, cf in res["other"]:
                    t.insert("end", "•  %s (CF %.2f)\n" % (self.kb.diagnosis_name(key), cf), "bullet")
        t.insert("end", "\n%d questions answered. Advice based on university extension guidance "
                        "(UC IPM, Iowa State, Univ. of Maryland).\n" % len(self.engine.history), "muted")
        t.configure(state="disabled")
        self.update_side()

    def _diag_block(self, t, item, kicker, title_tag):
        key, cf = item
        d = self.kb.diagnoses[key]
        t.insert("end", kicker + "\n", "kicker")
        t.insert("end", d["name"] + "\n", title_tag)
        t.insert("end", "Confidence: %s (certainty factor %.2f)\n" % (confidence_label(cf), cf), "conf")
        t.insert("end", "Why\n", "head")
        t.insert("end", d["explanation"] + "\n", "body")
        t.insert("end", "What to do\n", "head")
        for a in d["actions"]:
            t.insert("end", "•  " + a + "\n", "bullet")

    def show_how(self):
        res = self.engine.conclusion()
        keys = []
        if res["primary"]:
            keys = [res["primary"][0]] + [k for k, _ in res["co"]]
        items = []
        for k in keys:
            items.append(("== " + self.kb.diagnosis_name(k) + " ==", ""))
            for line in self.engine.explain_how(k):
                items.append((line, ""))
        if not items:
            items = [("No rule reached the reporting threshold.", "")]
        self._text_window("How the conclusion was reached",
                          "Rules that fired, in order, with the certainty factor after each:", items)

    def save_report(self):
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save diagnosis report", defaultextension=".txt",
            initialfile="plant_diagnosis.txt", filetypes=[("Text file", "*.txt")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(build_report(self.engine, show_how=True))
            fh.write("\n\n")
            fh.write(answers_summary(self.engine))
            fh.write("\n")
        messagebox.showinfo("Saved", "Report saved to:\n%s" % path, parent=self.root)

    # ------------------------------------------------------------ helpers
    def _text_window(self, title, intro, items):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=CARD)
        win.geometry("680x420")
        win.transient(self.root)
        tk.Label(win, text=title, font=self.f_head, bg=CARD, fg=INK).pack(anchor="w", padx=18, pady=(14, 0))
        tk.Label(win, text=intro, font=self.f_small, bg=CARD, fg=INK2).pack(anchor="w", padx=18, pady=(2, 6))
        frame = tk.Frame(win, bg=CARD)
        frame.pack(fill="both", expand=True, padx=18)
        t = tk.Text(frame, font=self.f_body, bg=CARD, fg=INK, wrap="word", relief="flat",
                    highlightthickness=0, spacing3=6)
        sb = tk.Scrollbar(frame, command=t.yview)
        t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        t.tag_configure("src", foreground=MUTED, font=self.f_small)
        for main, src in items:
            t.insert("end", main)
            if src:
                t.insert("end", "   [" + src + "]", "src")
            t.insert("end", "\n")
        t.configure(state="disabled")
        self._button(win, "Close", win.destroy).pack(anchor="e", padx=18, pady=12)
        win.bind("<Escape>", lambda e: win.destroy())
        self.last_window = win
        return win


def main():
    try:
        kb = KnowledgeBase(os.path.join(HERE, "knowledge_base.json"))
    except (ValueError, OSError) as e:
        print("Could not load knowledge base: %s" % e)
        return 1
    try:                                   # crisp text on high-DPI Windows screens
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    PlantDoctorGUI(root, kb)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
