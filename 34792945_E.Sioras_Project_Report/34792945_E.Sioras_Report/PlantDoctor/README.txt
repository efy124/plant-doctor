PLANT DOCTOR - A Rule-Based Expert System for Diagnosing Common Indoor Plant Problems
ICT206 Intelligent Systems - Project
Efthymios Sioras (34792945)
=====================================================================================

REQUIREMENTS
  - Windows 10 (also runs on macOS / Linux)
  - Python 3.8 or newer (https://www.python.org/downloads/ - tick "Add Python to PATH")
  - No other packages are needed to RUN the expert system.
  - matplotlib is needed only to redraw the evaluation charts:
        python -m pip install matplotlib

QUICK START (Windows)
  Double-click  run_gui.bat            - graphical interface (recommended)
  Double-click  run_plant_doctor.bat   - command-line consultation
  Double-click  run_evaluation.bat     - re-run the evaluation in the report

QUICK START (command prompt, from this folder)
  python gui.py                             graphical interface
  python plant_doctor.py                    interactive consultation
  python plant_doctor.py --demo             the example scenario from the proposal
  python plant_doctor.py --answers examples\fern_brown_tips.json
                                            non-interactive run from a JSON file
  python plant_doctor.py --check            validate the knowledge base
  python evaluate.py --set test             evaluation on the held-out test set
  python evaluate.py --set dev              evaluation on the development set
  python evaluate.py --no-charts            evaluation without matplotlib

USING THE GRAPHICAL INTERFACE
  Click an answer (or press its number key). The right-hand panel shows the
  leading diagnoses and their certainty factors, updated after every answer,
  and the answers given so far. Buttons: Don't know (U), Why this question?
  (W), Back (B), New plant. The results page shows the diagnosis, confidence,
  explanation and recommended actions; "How did you decide?" shows the rule
  trace and "Save report..." writes it to a text file.
  Tkinter is included with the standard Windows Python installer.

USING THE COMMAND-LINE CONSULTATION
  Answer each question by typing the option number and pressing Enter.
    u   don't know (the system reasons with what it has)
    w   why are you asking this? (shows the rules the question tests)
    h   help for this question
    b   back - undo the previous answer
    q   quit
  Only questions that can still change the result are asked (typically 16-25
  of the 29). At the end you get the most likely problem, any co-occurring
  problem, a confidence level, an explanation and recommended actions.
  After the result:  h = how the conclusion was reached (rule trace),
  a = your answers, s = save a text report, r = new plant, q = quit.

FILES
  gui.py                 graphical user interface (Tkinter)
  plant_doctor.py        command-line user interface
  engine.py              inference engine: forward chaining, MYCIN certainty
                         factors, goal-driven questioning, explanations
  knowledge_base.json    knowledge base: 29 questions, 87 rules, 16 diagnoses
                         (edit this file to add knowledge - no code changes)
  test_cases.json        10 development + 32 held-out test scenarios
  evaluate.py            evaluation harness (accuracy, baselines, coverage,
                         order independence, robustness, efficiency)
  examples\              sample answer file for --answers
  results\               evaluation outputs (CSV, summaries, PNG charts)
  results\v1_before_refinement\   results before the v2 refinement (first test run)

REPRODUCING THE REPORT
  Run  python evaluate.py --set test  - the numbers printed and the files in
  results\ (test_summary.txt, test_results.csv, charts_test\*.png) are the
  ones used in the report. Random trials use fixed seeds, so results repeat
  exactly.
