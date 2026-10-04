# Hypomnemata

**Your private hypomnemata: a terminal harness that turns raw journal
entries into a living wiki, using local LLMs only.**

> [!WARNING]
> **Hypomnemata is at a very early stage.** Two commands exist so far:
> create a journal entry, and file it.

*Hypomnemata* were the personal notebooks of the ancients: quotes,
reflections and daily notes kept for oneself, the practice behind Marcus
Aurelius' *Meditations*. This tool keeps that practice alive with a
twist: you dump raw thoughts, and local language models help you sort,
title, tag and compile them into a readable wiki.

## LLMs only where strictly necessary

Hypomnemata uses a language model **only for what nothing else can do**:
understanding meaning, proposing a title or tags, writing a summary.
Everything else — creating files, naming, dates, frontmatter, moving
files, checking links and formats — is done by **plain, deterministic code**: 100%
predictable, testable, and the same every time.

- **The model proposes, the code decides.** A model's output is a
  suggestion, validated against a strict schema before it touches
  anything.
- **Rules live in code, not in prompts.** Sources are immutable; nothing
  is filed or deleted without your confirmation. These guarantees are
  enforced by the program, not left to a model's goodwill.
- **Before adding an LLM call, ask whether a regular tool can do it.**
  If one can, it wins: cheaper, faster, and reliable.

## Principles

- **Your journal never leaves your machine.** Every model runs locally
  (through [Ollama](https://ollama.com)). No cloud, no account, no
  subscription.
- **Low friction in.** Write or dictate as thoughts come; titles and tags
  come afterwards, proposed by the system.
- **A minimal core.** A local [LLM wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
  and nothing more; specialised workflows are meant to live in separate
  plugins.
- **Plain files.** Your journal is a folder of Markdown files, readable in
  any editor or in Obsidian. Obsidian is not required.

## Try it

Requires [uv](https://docs.astral.sh/uv/), and [Ollama](https://ollama.com)
for title and tag proposals. Your second brain must be a Git repository.

```sh
cp config.example.toml config.local.toml   # then set your paths
cp models.example.toml models.local.toml   # then pick your local models
export EDITOR="codium --wait"              # any editor that waits until closed
uv run hypomnemata journal                 # write or dictate an entry
uv run hypomnemata format                  # punctuate and paragraph it
uv run hypomnemata triage                  # file it
```

`journal` creates an empty, dated entry with a random placeholder name
(`2026-10-03-curious-otter.md`) in `sources/inbox/` of your second brain,
and opens it in your editor with the cursor ready below the heading.

`format` punctuates and paragraphs the latest entry (save it first). A
small model proposes the formatting; the code checks that every word is
unchanged, in the same order, and rejects the proposal otherwise.

`triage` walks through the journal entries in the inbox. For each one, a
small local model proposes a title and tags; you accept them with Enter
or type your own. The entry is then renamed after its title, moved to
`sources/journal/` and committed — that file only.

Every action, every model call and every correction you make is recorded
in `var/log/audit.jsonl` (never versioned), so each run can be reviewed.

## Planned design

- **Core and interface kept apart.** `core/` does the work (files,
  models, commands); `tui/` (a [Textual](https://textual.textualize.io)
  terminal interface) only displays and calls the core. A graphical
  interface may follow later.
- **Model classes, not model names.** Commands ask for a class
  (`small`, `medium` or `large`, by parameter count); a config file maps
  each class to a local model. A machine runs the classes its memory
  allows; a command needing a class you don't have refuses clearly
  instead of silently degrading.
- **French first, English second.**

## License

[GNU AGPL-3.0](LICENSE).
