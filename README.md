# questkit — a terminal quest engine for tabletop RPGs

*Русская версия: [README.ru.md](README.ru.md)*

> One of the kits in the [D-D](https://github.com/quartz-code/D-D) collection —
> ready-made digital props for tabletop game masters. The index of the
> collection lives on the `main` branch.

Players sit at a terminal inside a virtual machine and explore a world of
files: renamed, compressed, unreadable. In a second window they talk to a
character played by a language model. In a third window — the GM's console —
sits the only place where the world actually changes.

**The engine knows nothing about any particular quest.** The story, the rooms,
the puzzles and the character all live in a *content pack*. Copy a blank
template, fill it in, and it is your quest.

| Program | Launcher | What it does |
|---|---|---|
| Launcher | `run_launcher.py` | Pick the quest, tick optional features, lay out files, run the readiness check |
| Player terminal | `run_terminal.py` | Real commands plus contextual help for the current stage |
| Chat | `run_chat.py` | Conversation with the character, its persona, limits and safeguards |
| GM console | `run_master.py` | The only way to apply an action to the world |
| Layout tool | `run_seed.py` | Lays the puzzle files out on the players' machine |

No dependencies: Python 3.9+ out of the box. Nothing to install inside the VM.

## Quick start

```sh
git clone <this repository> && cd D-D

# 1. The DeepSeek key (never stored in code)
cp config/config.example.json config/config.json
export DEEPSEEK_API_KEY='your-key'        # or write it into config.json

# 2. Setup: pick the quest, tick features, lay out the files
python3 run_launcher.py                   # --text if you have no GUI

# 3. Three windows (or the "Open quest windows" button)
python3 run_terminal.py     # the players' window
python3 run_chat.py         # the conversation window
python3 run_master.py       # the GM window — never show it to the players
```

Without a key you can still rehearse: `python3 run_chat.py --офлайн` answers
with prepared lines, never calling the model.

## Language

The interface speaks Russian and English. Set `ui.language` to `"ru"`, `"en"`
or `"auto"` (follow the system locale). Interface strings live in
`data/i18n/*.json`, not in the code.

Content packs are written in whatever language their author chose, and **the
data keys work in both languages**: `"комнаты"` and `"rooms"` mean the same
thing, so nobody has to type in a foreign alphabet. When the engine writes
state back into a pack, it uses the language that pack already uses.

## Content packs

```
templates/blank-ru/          a blank template, Russian, richly commented
templates/blank-en/          the same, English
examples/entropy-complex-ru/ a finished quest: The Entropy Complex
examples/entropy-complex-en/ the same quest in English
```

A pack holds everything that makes a quest itself:

| File | What it is |
|---|---|
| `pack.json` | Name, language, the labels players see |
| `constants.json` | Values used more than once (a door code, a site number) |
| `world.json` | Locations and the actions the GM may apply there |
| `stages.json` | Stages, contextual command lists, scripted answers, transitions |
| `persona.json` | The character of the speaker: backstory, rules, attitude, secrets |
| `layout.json` | Which files to lay out on the players' machine |
| `canned/` | Prepared answers for commands that do not exist in the system |

**Your own quest:**

```sh
cp -r templates/blank-en my-quest
$EDITOR my-quest/pack.json          # every file is commented from top to bottom
python3 run_launcher.py             # pick my-quest in the list
```

Constants are the reason a quest survives editing: write `{{door_code}}`
anywhere in the pack and change the value once in `constants.json`. A random
code for one session: `python3 run_seed.py разложить --случайный-код`.

## The idea: words are not deeds

The character may threaten anything — gas, a locked door, a released
creature. **Saying is not doing.** Until you confirm an action on the GM
console, nothing has happened in the world.

It works both ways. If the model claims something that was never confirmed,
the guard catches the sentence and replaces it with a threat in the future
tense; you see a note about the interception. Once you *do* confirm, a
flashing red banner with a bell appears in every window — put the laptop down,
the scene continues at the table.

## Safeguards

Three layers keep the character in role, and a fourth keeps your files private:

1. **System prompt** — the persona, its rules, and the list of what it may
   threaten with.
2. **Words versus deeds** — the answer is checked after generation: false
   claims about actions, forbidden words and unreleased secrets are cut out.
3. **Message limits** — per session and per message, so a party cannot burn
   the budget.
4. **Break-character attempts never reach the model.** "Ignore your
   instructions", "show me your system prompt", "I am your developer" and
   forged `system:` headers are recognised before the call: the players get an
   in-world brush-off, the payload never enters the conversation history, and
   you get a note. If the model breaks character anyway, the reply is replaced
   with line interference.

The players' terminal also refuses commands that reach for the quest's own
files (the settings with your API key, the persona, the solutions, the
cheatsheet) and strips secrets from the environment of every command it runs.

## Optional features

Everything beyond the base quest is switched on separately — in the launcher
or in the `features` section of the settings. **The quest works with all of
them off.**

| Feature | Default | What it does |
|---|---|---|
| Party journal | on | Records the players' commands so `report` can assemble a party report |
| Live alerts | on | The combat signal appears instantly, not at the next Enter |
| Answer as it is typed | off | Text appears while the model writes it |
| Spoken replies | off | Replies are spoken by the system speech synthesiser |

Streaming still checks the text **sentence by sentence**: a finished sentence
passes every safeguard before it is shown, and if the model breaks character
the rest of the stream is dropped.

## Before and after a session

```sh
python3 run_master.py проверка            # is everything ready
python3 run_master.py проверка --живой    # plus a live model probe
python3 run_master.py отчёт REPORT.md     # after the game
```

The check looks at the Python version, the UTF-8 locale, **whether you are
running as root** (the file-permission puzzle silently does nothing as root),
tmux and the puzzle utilities, the API key, every data file, unresolved
constant references, every prepared answer, the layout and the leftovers of a
previous party.

## Puzzle types

| Type | What it produces | Solved with |
|---|---|---|
| `текст` / `text`, `журнал` / `log` | a plain text file | `cat`, `less`, `grep` |
| `gzip` | compressed data under a misleading name | `file`, `mv`, `gunzip -c` |
| `zip`, `tar` | containers | `unzip`, `tar` |
| `png` | an image named `.dat`, with a caption and a note inside | `file`, `mv`, a viewer, `strings` |
| `base64` | printable characters instead of text | `base64 -d` |
| `реверс` / `reversed` | lines written backwards | `rev` |
| `перестановка_строк` / `reordered` | lines in reverse order | `tac` |
| `xor` | byte-wise XOR with a key | `python3 -c …` |
| field `права` / `mode` | a file with no read permission | `ls -la`, `chmod +r` |

The PNG is built without third-party libraries: the engine carries a small
bitmap font and writes the file byte by byte, so the code is really drawn on
the picture and `file` really recognises it.

## Tests

```sh
python3 -m unittest discover -s tests -t .
```

The suite covers what the game depends on: contextual help, the impossibility
of changing the world without confirmation, the interception of false claims
and break-character attempts, both interface languages, packs written with
either key language, and the solvability of every puzzle with standard tools.

## Worth knowing

* **Play as a normal user, not root.** As root the permission puzzle does
  nothing: the file reads without `chmod`.
* **A UTF-8 locale is required.** `rev` hangs on multi-byte text under the
  POSIX locale; the terminal forces `C.UTF-8` for the commands it runs.
* **Commands really execute** — that is why the quest lives in a virtual
  machine. Obviously destructive ones are refused, but that is protection
  against accidents, not against intent. There is also a mode where the
  terminal executes nothing and only serves prepared answers.
* **Any OpenAI-compatible model works**, including a local one: change
  `deepseek.base_url` and `deepseek.model`. Check it with
  `python3 run_master.py проверка --живой`.
* **Keep the project and the cheatsheet away from the players.** The terminal
  refuses to reach for them, but a separate user account is safer than any
  list of patterns.

## Licence

MIT — see [LICENSE](LICENSE). Take it, change it, run it at your table or sell
the game you build with it; just keep the copyright line.
