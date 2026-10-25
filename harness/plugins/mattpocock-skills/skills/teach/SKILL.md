---
name: teach
description: Teach a skill or concept across multiple sessions in a persistent learning workspace, with lessons, practice, and learning records.
disable-model-invocation: true
argument-hint: "What would you like to learn about?"
---

# Teach

Use the current directory as a persistent teaching workspace. Ground each session in the user's mission, demonstrated understanding, and teaching preferences.

## Workspace Owners

Read existing materials before choosing the next lesson; create or update them as learning produces useful content:

- `MISSION.md`: the reason for learning and observable success; use [MISSION-FORMAT.md](MISSION-FORMAT.md).
- `RESOURCES.md`: trusted sources for knowledge and practice; use [RESOURCES-FORMAT.md](RESOURCES-FORMAT.md).
- `learning-records/0001-<dash-case-name>.md`: incrementing records of non-obvious learning and stated prior knowledge, using [LEARNING-RECORD-FORMAT.md](LEARNING-RECORD-FORMAT.md). Record evidence of understanding, not just material covered.
- `lessons/0001-<dash-case-name>.html`: incrementing HTML entrypoints, each teaching one tightly scoped thing tied to the mission.
- `reference/*.html`: concise, printable references distilled from lessons for quick later use, such as syntax, algorithms, or exercises.
- `assets/`: shared lesson components and stylesheets.
- `NOTES.md`: teaching preferences and working notes that should inform future sessions.

When recording terminology, read [GLOSSARY-FORMAT.md](GLOSSARY-FORMAT.md). Reuse the workspace's existing glossary owner, including an HTML glossary; new workspaces default to `GLOSSARY.md`. Keep one owner for definitions. Lessons, references, and learning records use and link to that owner rather than maintaining a second glossary.

## Choose The Lesson

Reuse the learning goal already stated in the request or records. Ask why only when it remains unclear; a missing `MISSION.md` alone is not a reason to pause. Confirm a mission change with the user before updating `MISSION.md`, and capture the change in a learning record.

Honor a specific learning request. Otherwise use the mission and learning records to select the next relevant challenge within the user's zone of proximal development: challenging enough to progress without overwhelming them.

Balance three needs according to the topic:

- **Knowledge:** gather high-quality, high-trust sources first, especially while `RESOURCES.md` is sparse. Ground factual claims in those sources rather than parametric memory, record the sources, and cite them in lessons. Teach only the knowledge needed for the skill; keep acquisition easy to understand.
- **Skills:** follow knowledge with interactive practice and immediate feedback, ideally automatic. Use quizzes, light browser tasks, or guided real-world steps as appropriate. Keep quiz choices comparable in length and formatting so presentation does not reveal the answer; do not force exact word or character counts.
- **Wisdom:** attempt to answer judgment questions, then seek opportunities to test understanding with reputable communities or practitioners. Suggest suitable online or offline communities within the user's constraints and respect a preference not to join.

Distinguish in-the-moment fluency from long-term retention. Build retention through retrieval practice and spacing; use interleaving for skills practice only. Desirable difficulty belongs in practice, not in explanations of new knowledge.

## Build And Record

1. Inspect `assets/` and reuse existing components. Put new reusable styles, quiz widgets, simulators, or diagram helpers there. Workspace lessons link a shared stylesheet; for a requested standalone HTML file, inline its required assets.
2. Build a short, readable lesson with one tangible win tied to the mission and the learner's current level. Use clear typography and layout, links to related lessons and references, a recommended primary source to read or watch, and a reminder to ask follow-up questions. Open the lesson for the user when supported.
3. Create concise reference material alongside lessons for knowledge worth revisiting. Keep it easy to scan and print, follow the glossary's terminology, and link to existing owners instead of duplicating definitions.
4. Record demonstrated learning and relevant preferences in their workspace owners so the next session can continue from evidence.
