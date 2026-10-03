# Hypomnemata

**Your private hypomnemata: a terminal harness that turns raw journal
entries into a living wiki, using local LLMs only.**

> [!WARNING]
> **Hypomnemata is at a very early stage.** Nothing runs yet: this
> repository holds the design and, soon, a first skeleton.

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
