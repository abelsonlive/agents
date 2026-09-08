# Lesson Format

Lessons live in `./lessons/` as `0001-slug.html`, `0002-slug.html`, … Scan the directory for the highest number and increment. Each lesson is one self-contained HTML file, and the primary unit of teaching in the workspace.

## Shape

A lesson is short — one sitting, one win — and runs in this order:

1. **The win.** Open by naming what the user will be able to do by the end, and how it serves the mission.
2. **Just enough knowledge.** Only what this skill requires. Every claim carries an inline citation linking to its source in `RESOURCES.md`.
3. **Practice.** A feedback loop: a quiz, a light in-browser task, or a checklist of real-world steps (a pose to hold, a drill to run). The user acts and learns immediately how they did.
4. **Where next.** Anchors to related lessons and `reference/` docs, plus one **primary source** — the single best thing to read or watch on this topic.
5. **The teacher.** Close by reminding the user they can ask you followup questions about anything unclear.

## Components

Every lesson is assembled from `./assets/` — the shared stylesheet, quiz widgets, simulators, diagram helpers. Read that directory before authoring and build from what is already there, so the lessons read as one course rather than a pile of one-offs.

Anything a second lesson could reuse belongs in `assets/` as a component, linked rather than copied. The shared stylesheet is the first component every workspace earns.

## Craft

The user comes back to these, so make them beautiful: generous margins, a readable measure, restrained typography, and Tufte's habit of setting a figure beside the words that explain it. They should print cleanly.

## Quizzes

Give every answer to a question the same shape — same number of words, same length, same formatting — so the right one is found by knowing it, not by spotting the odd one out. Feedback lands the moment the user answers, and says why.
