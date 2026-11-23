# Swimming — audiobook

A reading of the preview edition of [Swimming: The art](https://github.com/whsbooks/swimming-book) by Wong Heung Sang, plus a 1920×1080 video ready to upload.

The voice is synthetic (Piper, `en_US-lessac-medium`), slowed slightly. It is a listening copy of the book, not a studio performance.

## Listen / upload

| File | What it is |
| --- | --- |
| `output/swimming-the-art-audiobook.m4a` | Full audiobook, AAC, about 7:53 |
| `output/swimming-the-art-audiobook.mp3` | Same reading, MP3 |
| `output/swimming-the-art-audiobook.wav` | Uncompressed master (22.05 kHz mono) |
| `output/chapters/` | One MP3 per chapter, 01–50 |
| `output/swimming-the-art-youtube.mp4` | 1920×1080, 30 fps, H.264 + AAC, about 7:54 |
| `output/youtube-description.txt` | Title, blurb, and chapter timestamps |
| `output/spoken-text.md` | The words that are read |
| `output/manifest.json` | Durations and narration for each chapter |

Suggested upload title:

**Swimming: The art — audiobook (preview edition) | Wong Heung Sang**

Paste `output/youtube-description.txt` into the description. The chapter lines (`0:10  Float`, and so on) are YouTube chapter markers. First marker is a few seconds in, which YouTube requires.

Cards use the book's colors: deep water `#0A3D62`, soft wave `#3C6382`, foam `#F5F7FA`. Each chapter shows the verse and, where the book has one, the explain-notes box.

## Rebuild

Needs the Piper binary and the lessac voice (already used from `/tmp/piper`), plus `ffmpeg` and `python3-cairo`.

```bash
python3 scripts/build_audiobook.py
```

The script reads `swimming-book.tex` (copied from the source repo), synthesizes one clip per chapter, then joins them.
