# Participant preparation (10 minutes before the workshop)

**Audience:** CTOs, architects, engineering managers, developers and founders. Pair programming is welcome; non-coders can follow the web UI.

**Prerequisites:** laptop, Python 3.11+, terminal, browser, ability to install dependencies. AWS account optional.

1. Clone the repository (or download it as a ZIP from GitHub and unzip it), `cd` into the repository folder, and run the `README.md` Quickstart.
2. Run `python -m lab.cli seed --reset` and `pytest -q`; expect `38 passed, 5 skipped` (the skipped tests make live AWS calls and run only when opted in).
3. Start `uvicorn lab.api:app --host 127.0.0.1 --port 8000` and open the local browser UI.
4. Keep two terminal windows: one for instructor commands, one for edits/tests.
5. If anything fails, work with a partner or follow the instructor's projected application.

**Do not:** put real customer data into the app, connect production bank APIs, publish the browser demo to the internet, or assume your laptop is physically in Nigeria without checking.
