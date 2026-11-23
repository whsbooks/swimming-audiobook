#!/usr/bin/env python3
"""Turn swimming-book.tex into a narrated audiobook and a YouTube video.

Narration is Piper (en_US lessac). Visuals are chapter cards in the book's
deep-water / foam palette, with a slow current so the frame is not a still.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import wave
from pathlib import Path

import cairo

ROOT = Path(__file__).resolve().parents[1]
TEX = ROOT / "swimming-book.tex"
BUILD = ROOT / "build"
AUDIO = ROOT / "audio"
OUT = ROOT / "output"

PIPER = Path("/tmp/piper/piper/piper")
VOICE = Path("/tmp/piper/voices/en_US-lessac-medium.onnx")

W, H = 1920, 1080
FPS = 30
SR = 22050

DEEP = (0x0A / 255, 0x3D / 255, 0x62 / 255)
SOFT = (0x3C / 255, 0x63 / 255, 0x82 / 255)
FOAM = (0xF5 / 255, 0xF7 / 255, 0xFA / 255)
NOTEBG = (0xEA / 255, 0xF0 / 255, 0xF4 / 255)
NOTELINE = (0x8F / 255, 0xAA / 255, 0xBB / 255)
INK = (0x14 / 255, 0x2A / 255, 0x3A / 255)

SERIF = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
SERIF_I = "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"
SERIF_B = "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"
SANS = "/usr/share/fonts/truetype/lato/Lato-Regular.ttf"
SANS_L = "/usr/share/fonts/truetype/lato/Lato-Light.ttf"
SANS_B = "/usr/share/fonts/truetype/lato/Lato-Bold.ttf"


def parse_book(tex: str) -> list[dict]:
    body = tex.split(r"\mainmatter", 1)[1]
    body = body.split(r"\end{document}", 1)[0]
    parts = re.split(r"\\chapter\{", body)
    chapters = []
    for part in parts[1:]:
        title, rest = part.split("}", 1)
        verses = re.findall(
            r"\\Large\\itshape\\color\{deepwater\}\s*(.+?)\}", rest, flags=re.S
        )
        verses = [re.sub(r"\s+", " ", v).strip() for v in verses]
        notes = []
        box = re.search(r"\\explannotebox\{(.*?)\\chapter|\\explannotebox\{(.*)\Z", rest, flags=re.S)
        # notes live only inside this chapter chunk already
        for item in re.findall(r"\\item\s+(.+)", rest):
            item = re.sub(r"\\[a-zA-Z]+", " ", item)
            item = item.replace("{", " ").replace("}", " ")
            item = re.sub(r"\s+", " ", item).strip()
            if item:
                notes.append(item)
        chapters.append({"title": title.strip(), "verses": verses, "notes": notes})
    return chapters


def narration_for(ch: dict, n: int, total: int) -> str:
    bits = [f"Chapter {n}. {ch['title']}."]
    bits.extend(ch["verses"])
    if ch["notes"]:
        bits.append("Explain notes.")
        bits.extend(ch["notes"])
    return " ".join(bits)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def synth(text: str, dest: Path, length_scale: float = 1.08) -> float:
    return synth_stdin(text, dest, length_scale=length_scale)


def synth_stdin(text: str, dest: Path, length_scale: float = 1.08, silence: float = 0.55) -> float:
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            str(PIPER),
            "--model",
            str(VOICE),
            "--output_file",
            str(dest),
            "--length_scale",
            str(length_scale),
            "--sentence_silence",
            str(silence),
        ],
        input=text.encode(),
        check=True,
        stdout=subprocess.DEVNULL,
    )
    del proc
    return wav_duration(dest)


def silence_wav(dest: Path, seconds: float) -> None:
    n = int(SR * seconds)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"\x00\x00" * n)


def concat_wavs(paths: list[Path], dest: Path) -> float:
    """Concatenate 22050 Hz mono s16 wavs."""
    frames = bytearray()
    for p in paths:
        with wave.open(str(p), "rb") as w:
            assert w.getframerate() == SR
            assert w.getnchannels() == 1
            frames.extend(w.readframes(w.getnframes()))
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(frames)
    return len(frames) / 2 / SR


def font_metrics(cr: cairo.Context) -> tuple[float, float, float, float, float]:
    ext = cr.font_extents()
    if isinstance(ext, tuple):
        return ext  # ascent, descent, height, max_x_advance, max_y_advance
    return ext.ascent, ext.descent, ext.height, ext.max_x_advance, ext.max_y_advance


def text_width(cr: cairo.Context, text: str) -> float:
    ext = cr.text_extents(text)
    if isinstance(ext, tuple):
        return ext[2]
    return ext.width


def wrap_text(cr: cairo.Context, text: str, max_w: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = word if not cur else cur + " " + word
        if text_width(cr, trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


_FACES = {
    SERIF: ("Liberation Serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL),
    SERIF_I: ("Liberation Serif", cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_NORMAL),
    SERIF_B: ("Liberation Serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD),
    SANS: ("Lato", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL),
    SANS_L: ("Lato Light", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL),
    SANS_B: ("Lato", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD),
}


def set_font(cr: cairo.Context, path: str, size: float) -> None:
    family, slant, weight = _FACES[path]
    cr.select_font_face(family, slant, weight)
    cr.set_font_size(size)


def paint_water(cr: cairo.Context, t: float) -> None:
    cr.set_source_rgb(*FOAM)
    cr.paint()
    # soft vertical wash
    grad = cairo.LinearGradient(0, 0, 0, H)
    grad.add_color_stop_rgb(0.0, 0.93, 0.96, 0.98)
    grad.add_color_stop_rgb(0.55, *FOAM)
    grad.add_color_stop_rgb(1.0, 0.86, 0.91, 0.94)
    cr.set_source(grad)
    cr.paint()
    # slow currents
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for i in range(7):
        y0 = 80 + i * 150
        phase = t * (0.15 + i * 0.02) + i * 0.9
        cr.new_path()
        x = -40
        cr.move_to(x, y0)
        while x < W + 40:
            y = y0 + math.sin(x * 0.004 + phase) * (18 + i * 2) + math.sin(x * 0.011 - phase) * 6
            cr.line_to(x, y)
            x += 24
        alpha = 0.10 + 0.03 * math.sin(phase)
        cr.set_source_rgba(0x3C / 255, 0x63 / 255, 0x82 / 255, alpha)
        cr.set_line_width(1.6 + (i % 3) * 0.6)
        cr.stroke()


def draw_centered(cr: cairo.Context, text: str, y: float, font: str, size: float, rgb, max_w: float = 1500) -> float:
    set_font(cr, font, size)
    cr.set_source_rgb(*rgb)
    lines = wrap_text(cr, text, max_w)
    ascent, _descent, height, _mx, _my = font_metrics(cr)
    line_h = height * 1.15
    total_h = line_h * len(lines)
    yy = y - total_h / 2 + ascent
    for line in lines:
        tw = text_width(cr, line)
        cr.move_to((W - tw) / 2, yy)
        cr.show_text(line)
        yy += line_h
    return total_h


def render_frame(path: Path, kind: str, payload: dict, t: float, progress: float) -> None:
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    cr = cairo.Context(surf)
    paint_water(cr, t)

    # progress hairline
    cr.set_source_rgba(*SOFT, 0.35)
    cr.rectangle(0, H - 8, W * progress, 8)
    cr.fill()

    if kind == "title":
        draw_centered(cr, "SWIMMING", 430, SERIF_B, 92, DEEP, 1600)
        cr.set_source_rgba(*SOFT, 0.7)
        cr.set_line_width(1.2)
        cr.move_to(W / 2 - 90, 500)
        cr.line_to(W / 2 + 90, 500)
        cr.stroke()
        draw_centered(cr, "The art", 560, SERIF_I, 42, SOFT)
        draw_centered(cr, "Wong Heung Sang", 680, SANS, 32, DEEP)
        draw_centered(cr, "Preview edition  ·  audiobook", 760, SANS_L, 24, SOFT)
    elif kind == "chapter":
        ch = payload
        # kicker
        set_font(cr, SANS, 26)
        cr.set_source_rgb(*SOFT)
        kicker = f"CHAPTER  {ch['n']:02d}   ·   {ch['n']} OF {ch['total']}"
        tw = text_width(cr, kicker)
        cr.move_to((W - tw) / 2, 210)
        cr.show_text(kicker)

        title_size = 78 if len(ch["title"]) < 18 else 62
        draw_centered(cr, ch["title"], 300, SERIF_B, title_size, DEEP, 1600)

        cr.set_source_rgba(*SOFT, 0.55)
        cr.set_line_width(1.0)
        cr.move_to(W / 2 - 70, 360)
        cr.line_to(W / 2 + 70, 360)
        cr.stroke()

        # verses
        y = 470
        set_font(cr, SERIF_I, 40)
        verse_lines = []
        for v in ch["verses"]:
            verse_lines.extend(wrap_text(cr, v, 1460))
            verse_lines.append("")  # gap between verses
        if verse_lines and verse_lines[-1] == "":
            verse_lines.pop()
        ext_ascent, _d, ext_h, _mx, _my = font_metrics(cr)
        line_h = ext_h * 1.2
        block_h = line_h * max(1, len(verse_lines))
        y = 430 + max(0, (280 - block_h) / 2) + ext_ascent
        cr.set_source_rgb(*DEEP)
        for line in verse_lines:
            if not line:
                y += line_h * 0.45
                continue
            tw = text_width(cr, line)
            cr.move_to((W - tw) / 2, y)
            cr.show_text(line)
            y += line_h

        if ch["notes"]:
            # note card
            notes_joined = ch["notes"]
            set_font(cr, SANS, 28)
            wrapped = []
            for note in notes_joined:
                wrapped.append(wrap_text(cr, "·  " + note, 1320))
            nrows = sum(len(w) for w in wrapped)
            extn_ascent, _d, extn_h, _mx, _my = font_metrics(cr)
            nh = extn_h * 1.25
            pad_y = 28
            card_h = pad_y * 2 + 36 + nh * nrows
            card_w = 1480
            card_x = (W - card_w) / 2
            card_y = min(y + 36, H - card_h - 70)
            cr.set_source_rgb(*NOTEBG)
            cr.rectangle(card_x, card_y, card_w, card_h)
            cr.fill()
            cr.set_source_rgb(*NOTELINE)
            cr.set_line_width(1)
            cr.rectangle(card_x, card_y, card_w, card_h)
            cr.stroke()
            set_font(cr, SANS_B, 20)
            cr.set_source_rgb(*DEEP)
            label = "EXPLAIN NOTES"
            cr.move_to(card_x + 36, card_y + 36)
            cr.show_text(label)
            cr.set_source_rgb(*NOTELINE)
            cr.set_line_width(0.8)
            cr.move_to(card_x + 36, card_y + 50)
            cr.line_to(card_x + card_w - 36, card_y + 50)
            cr.stroke()
            set_font(cr, SANS, 28)
            cr.set_source_rgb(*INK)
            yy = card_y + 50 + extn_ascent + 16
            for group in wrapped:
                for line in group:
                    cr.move_to(card_x + 36, yy)
                    cr.show_text(line)
                    yy += nh
                yy += 6
    elif kind == "end":
        draw_centered(cr, "Swimming", 430, SERIF_B, 72, DEEP)
        draw_centered(cr, "The art", 530, SERIF_I, 36, SOFT)
        draw_centered(cr, "Wong Heung Sang", 640, SANS, 30, DEEP)
        draw_centered(cr, "Preview edition", 720, SANS_L, 24, SOFT)
        draw_centered(cr, "github.com/whsbooks/swimming-book", 820, SANS, 22, SOFT)
    else:
        raise ValueError(kind)

    # footer
    set_font(cr, SANS_L, 20)
    cr.set_source_rgba(*SOFT, 0.85)
    foot = "Swimming  ·  The art  ·  Wong Heung Sang"
    tw = text_width(cr, foot)
    cr.move_to((W - tw) / 2, H - 36)
    cr.show_text(foot)

    surf.write_to_png(str(path))


def clip_from_still(png: Path, wav: Path, mp4: Path, zoom_in: bool = False) -> float:
    """One keyframe, then skip-frames, so the card cannot drift and stays small."""
    del zoom_in
    dur = wav_duration(wav)
    nframes = max(2, int(math.ceil(dur * FPS - 1e-6)))
    hold = nframes / FPS
    still = mp4.with_suffix(".still.mp4")
    # a 2-frame clip: real picture, then a skip frame that points at it
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            str(FPS),
            "-i",
            str(png),
            "-frames:v",
            "2",
            "-vf",
            "format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "stillimage",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "300",
            "-bf",
            "0",
            "-x264-params",
            "keyint=300:min-keyint=300:scenecut=0:bframes=0",
            "-an",
            str(still),
        ]
    )
    # re-encode the loop so only the first frame is a keyframe; the rest are skips
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-stream_loop",
            str(nframes),
            "-i",
            str(still),
            "-i",
            str(wav),
            "-vf",
            "format=yuv420p",
            "-af",
            "apad,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "stillimage",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(nframes + 5),
            "-bf",
            "0",
            "-x264-params",
            f"keyint={nframes + 5}:min-keyint={nframes + 5}:scenecut=0:bframes=0",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "44100",
            "-t",
            f"{hold:.3f}",
            "-movflags",
            "+faststart",
            str(mp4),
        ]
    )
    still.unlink(missing_ok=True)
    return hold


def main() -> None:
    chapters = parse_book(TEX.read_text())
    if len(chapters) != 50:
        raise SystemExit(f"expected 50 chapters, got {len(chapters)}")
    for i, ch in enumerate(chapters, 1):
        if not ch["verses"]:
            raise SystemExit(f"chapter {i} {ch['title']!r} has no verse")

    AUDIO.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    frames = BUILD / "frames"
    clips = BUILD / "clips"
    frames.mkdir(exist_ok=True)
    clips.mkdir(exist_ok=True)

    segments: list[dict] = []

    # opening
    intro = (
        "Swimming. The art. By Wong Heung Sang. Preview edition. "
        "An audiobook in fifty short chapters."
    )
    intro_wav = AUDIO / "00-opening.wav"
    print("synth opening")
    synth_stdin(intro, intro_wav, length_scale=1.12, silence=0.65)
    pad = AUDIO / "00-pad.wav"
    silence_wav(pad, 0.8)
    intro_full = AUDIO / "00-opening-full.wav"
    intro_dur = concat_wavs([intro_wav, pad], intro_full)
    segments.append({"kind": "title", "wav": intro_full, "dur": intro_dur, "n": 0})

    manifest_ch = []
    for i, ch in enumerate(chapters, 1):
        text = narration_for(ch, i, len(chapters))
        wav = AUDIO / f"{i:02d}-{slug(ch['title'])}.wav"
        print(f"synth {i:02d} {ch['title']}")
        spoken = narration_for(ch, i, len(chapters))
        if ch["notes"] and not spoken.endswith("."):
            spoken += "."
        synth_stdin(spoken, wav, length_scale=1.06, silence=0.62)
        tail = AUDIO / f"{i:02d}-tail.wav"
        silence_wav(tail, 0.85)
        full = AUDIO / f"{i:02d}-full.wav"
        dur = concat_wavs([wav, tail], full)
        segments.append(
            {
                "kind": "chapter",
                "wav": full,
                "dur": dur,
                "n": i,
                "title": ch["title"],
                "verses": ch["verses"],
                "notes": ch["notes"],
                "total": len(chapters),
            }
        )
        manifest_ch.append(
            {
                "n": i,
                "title": ch["title"],
                "verses": ch["verses"],
                "notes": ch["notes"],
                "narration": spoken,
                "audio": str(full.relative_to(ROOT)),
                "seconds": round(dur, 2),
            }
        )

    close = (
        "End of the preview edition of Swimming, The art, by Wong Heung Sang. "
        "The text is at github.com slash whsbooks slash swimming dash book."
    )
    close_wav = AUDIO / "51-closing.wav"
    print("synth closing")
    synth_stdin(close, close_wav, length_scale=1.12, silence=0.6)
    close_pad = AUDIO / "51-pad.wav"
    silence_wav(close_pad, 1.2)
    close_full = AUDIO / "51-closing-full.wav"
    close_dur = concat_wavs([close_wav, close_pad], close_full)
    segments.append({"kind": "end", "wav": close_full, "dur": close_dur, "n": 51})

    # full audiobook wav + m4a/mp3
    print("concat audiobook")
    book_wav = OUT / "swimming-the-art-audiobook.wav"
    total = concat_wavs([s["wav"] for s in segments], book_wav)
    book_m4a = OUT / "swimming-the-art-audiobook.m4a"
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(book_wav),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "44100",
            "-movflags",
            "+faststart",
            str(book_m4a),
        ]
    )
    book_mp3 = OUT / "swimming-the-art-audiobook.mp3"
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(book_wav),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(book_mp3),
        ]
    )

    # per-chapter chapter files already in audio/; also copy clean chapter mp3s
    ch_dir = OUT / "chapters"
    ch_dir.mkdir(exist_ok=True)
    for item in manifest_ch:
        src = ROOT / item["audio"]
        mp3 = ch_dir / f"{item['n']:02d}-{slug(item['title'])}.mp3"
        run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "2",
                str(mp3),
            ]
        )
        item["mp3"] = str(mp3.relative_to(ROOT))

    # video cards + clips
    print("render cards")
    list_path = BUILD / "concat.txt"
    lines = []
    acc = 0.0
    timeline = []
    for i, seg in enumerate(segments):
        png = frames / f"{i:02d}.png"
        payload = {}
        if seg["kind"] == "chapter":
            payload = seg
        render_frame(png, seg["kind"], payload, t=i * 1.7, progress=acc / max(total, 1))
        mp4 = clips / f"{i:02d}.mp4"
        print(f"clip {i:02d} {seg['dur']:.1f}s")
        hold = clip_from_still(png, seg["wav"], mp4)
        lines.append(f"file '{mp4}'")
        timeline.append(
            {
                "index": i,
                "kind": seg["kind"],
                "title": seg.get("title", seg["kind"]),
                "start": round(acc, 3),
                "seconds": round(hold, 3),
            }
        )
        acc += hold

    list_path.write_text("\n".join(lines) + "\n")
    video = OUT / "swimming-the-art-youtube.mp4"
    print("concat video")
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(video),
        ]
    )

    meta = {
        "title": "Swimming: The art",
        "author": "Wong Heung Sang",
        "edition": "Preview edition",
        "source": "https://github.com/whsbooks/swimming-book",
        "voice": "Piper en_US-lessac-medium (length_scale 1.06)",
        "chapters": len(chapters),
        "audiobook_seconds": round(total, 2),
        "youtube": str(video.relative_to(ROOT)),
        "m4a": str(book_m4a.relative_to(ROOT)),
        "mp3": str(book_mp3.relative_to(ROOT)),
        "timeline": timeline,
        "chapter_audio": manifest_ch,
    }
    (OUT / "manifest.json").write_text(json.dumps(meta, indent=2) + "\n")
    write_description(meta)
    write_chapters_md(manifest_ch)
    print(f"done {total:.1f}s -> {video}")


def slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "chapter"


def write_description(meta: dict) -> None:
    lines = [
        "Swimming: The art — audiobook",
        "Wong Heung Sang  ·  Preview edition",
        "",
        "A reading of the preview edition.",
        "Source text: https://github.com/whsbooks/swimming-book",
        "",
        "Voice: Piper, en_US lessac (medium), slowed slightly.",
        "This is a synthetic reading for listening along with the book, not a studio performance.",
        "",
        "Chapters",
        "",
    ]
    t = 0.0
    # timeline includes opening at 0
    for item in meta["timeline"]:
        if item["kind"] != "chapter":
            continue
        lines.append(f"{fmt_ts(item['start'])}  {item['title']}")
    lines += [
        "",
        "Suggested YouTube title:",
        "Swimming: The art — audiobook (preview edition) | Wong Heung Sang",
        "",
        "Tags: swimming, audiobook, Wong Heung Sang, swimming book, freestyle, meditation",
        "",
    ]
    (OUT / "youtube-description.txt").write_text("\n".join(lines) + "\n")


def write_chapters_md(chapters: list[dict]) -> None:
    lines = ["# Swimming: The art — spoken text", "", "Preview edition. Wong Heung Sang.", ""]
    for ch in chapters:
        lines.append(f"## {ch['n']}. {ch['title']}")
        lines.append("")
        for v in ch["verses"]:
            lines.append(f"> {v}")
            lines.append("")
        if ch["notes"]:
            lines.append("Explain notes:")
            lines.append("")
            for n in ch["notes"]:
                lines.append(f"- {n}")
            lines.append("")
    (OUT / "spoken-text.md").write_text("\n".join(lines) + "\n")


def fmt_ts(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


if __name__ == "__main__":
    main()
