"""Word (.docx) rendering of a player's game-week entry.

Mirrors the paper "Charity Tipster" form (see exampleform.pdf) so the online
half of the game can print/email an identical sheet: the four sections, the
player's predictions filled in, and the scoring boxes left blank for marking.

`build_entry_docx()` returns the .docx as bytes (built in memory — nothing hits
disk, which matters on serverless). `entry_completeness()` is the gate the views
and template use to only offer download/email once the form is actually filled.
"""

from __future__ import annotations

import io

from django.utils import timezone

from .models import Entry

# Scoring legends, lifted verbatim from the paper form.
_SECTION1_LEGEND = (
    "3pts Home Win, 4pts Draw, 5pts Away Win plus [5pts Bonus for Correct Result "
    "totalling 0–4 goals or 7pts for Correct Result totalling 5 or more goals]."
)
_SECTION2_LEGEND = (
    "(5 points exactly correct: 3 pts for +/- 1 Goal: 2 pts for +/- 2 Goals: "
    "1 pt for +/- 3 Goal)"
)
_SECTION4_POINTS = {1: "4 Points", 2: "3 Points", 3: "2 Points", 4: "1 Point"}


def entry_completeness(participant, game_week):
    """Return (entry, missing) where `missing` is a list of human labels.

    The form counts as complete when every match has both scores, the total-goals
    box is filled, and all four scorers are named. True/False always has a value
    (it defaults to True), so it never blocks. `entry` is None when nothing has
    been saved yet.
    """
    entry = (
        Entry.objects.filter(participant=participant, game_week=game_week)
        .prefetch_related("match_predictions", "scorer_picks")
        .first()
    )
    if entry is None:
        return None, ["Save your predictions first"]

    missing = []
    preds = {mp.fixture_id: mp for mp in entry.match_predictions.all()}
    unscored = 0
    for fixture in game_week.fixtures.all():
        mp = preds.get(fixture.id)
        if mp is None or mp.pred_home is None or mp.pred_away is None:
            unscored += 1
    if unscored:
        missing.append(f"{unscored} match score(s)")

    tgp = getattr(entry, "total_goals_prediction", None)
    if tgp is None or tgp.predicted_total is None:
        missing.append("total goals")

    named = sum(1 for p in entry.scorer_picks.all() if (p.player_name or "").strip())
    if named < 4:
        missing.append(f"{4 - named} scorer pick(s)")

    return entry, missing


def _shade(cell, hex_fill):
    """Apply a background fill to a table cell (python-docx has no direct API)."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _bold(cell):
    for p in cell.paragraphs:
        for r in p.runs:
            r.font.bold = True


def build_entry_docx(participant, game_week) -> bytes:
    """Render `participant`'s entry for `game_week` as a .docx byte string."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    entry = (
        Entry.objects.filter(participant=participant, game_week=game_week)
        .prefetch_related(
            "match_predictions", "tf_answers", "scorer_picks"
        )
        .first()
    )
    preds = {mp.fixture_id: mp for mp in entry.match_predictions.all()} if entry else {}
    tf = {a.question_id: a.answer for a in entry.tf_answers.all()} if entry else {}
    scorers = {p.position: p.player_name for p in entry.scorer_picks.all()} if entry else {}
    tgp = getattr(entry, "total_goals_prediction", None) if entry else None

    doc = Document()

    # --- Header block ---------------------------------------------------------
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(game_week.title or "THE CHARITY TIPSTER")
    run.bold = True
    run.font.size = Pt(18)
    for line, size in ((f"Week {game_week.week_number}", 14), (game_week.date_range_label, 13)):
        if not line:
            continue
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(line)
        r.bold = True
        r.font.size = Pt(size)

    # --- Section 1: match scores ---------------------------------------------
    fixtures = list(game_week.fixtures.all())
    t1 = doc.add_table(rows=1, cols=6)
    t1.style = "Table Grid"
    hdr = t1.rows[0].cells
    for cell, text in zip(hdr, ["Home", "", "Away", "", "Kick-off", "Score"]):
        cell.text = text
        _bold(cell)
        _shade(cell, "D9D9D9")
    for fixture in fixtures:
        mp = preds.get(fixture.id)
        h = "" if not mp or mp.pred_home is None else str(mp.pred_home)
        a = "" if not mp or mp.pred_away is None else str(mp.pred_away)
        ko = ""
        if fixture.kickoff:
            ko = timezone.localtime(fixture.kickoff).strftime("%a %H:%M")
        cells = t1.add_row().cells
        cells[0].text = fixture.home_team
        cells[1].text = h
        cells[2].text = fixture.away_team
        cells[3].text = a
        cells[4].text = ko
        cells[5].text = ""  # scoring box, left blank for marking
    doc.add_paragraph(_SECTION1_LEGEND).runs[0].font.size = Pt(9)
    doc.add_paragraph()

    # --- Section 2: total goals ----------------------------------------------
    doc.add_paragraph().add_run(
        "Total Number of Goals Scored in these 10 matches"
    ).bold = True
    t2 = doc.add_table(rows=1, cols=2)
    t2.style = "Table Grid"
    t2.rows[0].cells[0].text = (
        "" if not tgp or tgp.predicted_total is None else str(tgp.predicted_total)
    )
    t2.rows[0].cells[1].text = "Score:"
    doc.add_paragraph(_SECTION2_LEGEND).runs[0].font.size = Pt(9)
    doc.add_paragraph()

    # --- Section 3: true / false ---------------------------------------------
    doc.add_paragraph().add_run("True / False (20 points for all 8 correct)").bold = True
    questions = list(game_week.questions.all())
    t3 = doc.add_table(rows=1, cols=4)
    t3.style = "Table Grid"
    for cell, text in zip(t3.rows[0].cells, ["Question", "True", "False", "Score"]):
        cell.text = text
        _bold(cell)
        _shade(cell, "D9D9D9")
    for q in questions:
        ans = tf.get(q.id)
        cells = t3.add_row().cells
        cells[0].text = q.text
        cells[1].text = "X" if ans is True else ""
        cells[2].text = "X" if ans is False else ""
        cells[3].text = ""
    doc.add_paragraph(
        "2pts for each correct answer and a bonus of 4pts if you get them all correct"
    ).runs[0].font.size = Pt(9)
    doc.add_paragraph()

    # --- Section 4: scorers ---------------------------------------------------
    p4 = doc.add_paragraph()
    p4.add_run("Predict the Scorers: ").bold = True
    p4.add_run("bonus of 1pt for any extra goals scored by your selection").font.size = Pt(9)
    t4 = doc.add_table(rows=1, cols=3)
    t4.style = "Table Grid"
    for cell, text in zip(t4.rows[0].cells, ["Points", "Scorer and Team", "Score"]):
        cell.text = text
        _bold(cell)
        _shade(cell, "D9D9D9")
    for position in range(1, 5):
        cells = t4.add_row().cells
        cells[0].text = _SECTION4_POINTS[position]
        cells[1].text = scorers.get(position, "") or ""
        cells[2].text = ""
    doc.add_paragraph()

    # --- Name + footer --------------------------------------------------------
    name = doc.add_paragraph()
    name.add_run("Name: ").bold = True
    name.add_run(participant.display_name)

    return _to_bytes(doc)


def _to_bytes(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
