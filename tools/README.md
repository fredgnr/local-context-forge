# Handbook builder

The printable Chinese handbook is generated from `docs/00-*.md` through
`docs/13-*.md`.

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
