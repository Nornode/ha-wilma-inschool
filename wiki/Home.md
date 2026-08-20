# Wilma for Home Assistant Wiki

This wiki documents what the Wilma Home Assistant integration can do, what to expect from it, and how to maintain the GitHub Wiki from version-controlled Markdown files in this repository.

## What This Integration Does

Wilma for Home Assistant connects to a Wilma school account and creates Home Assistant devices and entities for the students available to that account. It is aimed at practical household automations: notifications for new school messages, quick schedule visibility, bulletin updates, and attendance monitoring.

Core features:

- One Home Assistant device per discovered student profile.
- Sensors for latest messages, unread message count, latest bulletins, unread bulletin count, next lesson, attendance marks, latest attendance mark, and last successful update.
- A calendar entity per student for the timetable.
- Events for new messages, new bulletins, and new attendance marks.
- A diagnostic problem binary sensor when refreshes fail or partial fetch errors occur.
- English, Finnish, and Swedish UI translations.

## Wiki Version Control

GitHub Wikis are separate git repositories. For this repository, the live wiki repository is:

```bash
https://github.com/Nornode/ha-wilma-inschool.wiki.git
```

The files in this `wiki/` directory are source files that can be committed with the main integration. To publish them to the GitHub Wiki, copy or sync the Markdown files into a clone of the wiki repository and push there.

Example publish flow:

```bash
git clone https://github.com/Nornode/ha-wilma-inschool.wiki.git ../ha-wilma-inschool.wiki
rsync -av --delete wiki/ ../ha-wilma-inschool.wiki/
cd ../ha-wilma-inschool.wiki
git add .
git commit -m "Update wiki"
git push
```

This gives you both forms of history: normal reviewable changes in the main repository, and the live GitHub Wiki history in the `.wiki.git` repository.

## Pages

- [[What to Expect]]
- [[Installation and Setup]]
- [[Entities and Events]]
- [[Automation Examples]]
- [[Development]]
