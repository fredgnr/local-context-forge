# Handbook builder

The printable Chinese handbook is generated from every numbered
`docs/[0-9][0-9]-*.md` file, in lexical order. At the current documentation
revision that is `docs/00-*.md` through `docs/18-*.md`.

The handbook is a generated convenience copy. The live handoff authorities are
[`docs/development/status.md`](../docs/development/status.md),
[`docs/development/todo.md`](../docs/development/todo.md), and
[`docs/development/traceability.md`](../docs/development/traceability.md);
regenerate the PDF after changing numbered chapters, and never treat an old PDF
as newer evidence than those version-controlled files.

```bash
python3 -m pip install -r tools/requirements.txt
python3 tools/build_handbook.py
```

Output:

```text
output/pdf/Local-Context-Forge-Handbook.pdf
```

`NotoSansSC-Regular.ttf` is bundled so Chinese glyphs are embedded and the PDF
renders consistently on machines without a CJK system font. The font is
distributed under the SIL Open Font License; see `OFL-NotoSansSC.txt`.
