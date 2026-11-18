#!/usr/bin/env python3
"""words.json -> animated .ass captions (+ plain .srt).

Each spoken word becomes its own subtitle event, so the active word can be
recoloured and scaled ("pop") in sync with speech - the TikTok/Shorts look.
ASS is rendered by ffmpeg's libass, so no video editor is needed.
"""
import argparse
import json
import re

# name: (max_words_per_chunk, animation, uppercase)
STYLES = {
    "pop":      (3, "pop", True),      # 3 words on screen, active one pops + recolours
    "bounce":   (3, "bounce", True),   # same but with an overshoot bounce
    "karaoke":  (6, "none", False),    # a full phrase, active word recoloured
    "word":     (1, "pop", True),      # one big word at a time
}


def ass_color(hex_rgb, alpha=0):
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper().replace("&H", "&H")


def ts(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def srt_ts(t):
    ms = int(round(max(0.0, t) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def esc(text):
    text = text.replace("\\", "").replace("{", "(").replace("}", ")")
    return re.sub(r"\s+", " ", text)


def chunk_words(words, max_words, max_chars=18, gap=0.6):
    chunks, cur = [], []
    for w in words:
        if cur:
            too_long = len(cur) >= max_words or sum(len(x["w"]) + 1 for x in cur) + len(w["w"]) > max_chars * (2 if max_words > 3 else 1)
            pause = w["s"] - cur[-1]["e"] > gap
            sentence_end = cur[-1]["w"][-1] in ".?!"
            if too_long or pause or sentence_end:
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def build(words, width, height, style="pop", font="Arial", fontsize=None, color="#FFFFFF",
          highlight="#FFD400", outline_color="#000000", position=0.72, uppercase=None):
    max_words, anim, upper = STYLES[style]
    if uppercase is not None:
        upper = uppercase
    vertical = height > width
    fontsize = fontsize or round(width * (0.085 if vertical else 0.05))
    if style == "word":
        fontsize = round(fontsize * 1.35)
    outline = max(3, round(fontsize * 0.075))
    margin_v = round(height * (1 - position))  # distance from bottom to the text baseline
    margin_lr = round(width * 0.06)

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{fontsize},{ass_color(color)},{ass_color(highlight)},{ass_color(outline_color)},&H80000000,-1,0,0,0,100,100,0,0,1,{outline},2,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    hl = ass_color(highlight)
    pop = r"{\c" + hl + r"\fscx82\fscy82\t(0,90,\fscx112\fscy112)}"
    bounce = r"{\c" + hl + r"\fscx70\fscy70\t(0,80,\fscx128\fscy128)\t(80,160,\fscx108\fscy108)}"
    plain_hl = r"{\c" + hl + "}"
    reset = r"{\r}"
    lines = []
    chunks = chunk_words(words, max_words)
    for ci, ch in enumerate(chunks):
        nxt_start = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else None
        for i, w in enumerate(ch):
            start = w["s"]
            if i + 1 < len(ch):
                end = ch[i + 1]["s"]
            else:
                end = w["e"] + 0.25
                if nxt_start is not None:
                    end = min(end, nxt_start)
            end = max(end, start + 0.06)
            parts = []
            for j, x in enumerate(ch):
                t = esc(x["w"])
                t = t.upper() if upper else t
                if j == i:
                    tag = {"pop": pop, "bounce": bounce}.get(anim, plain_hl)
                    parts.append(tag + t + reset)
                else:
                    parts.append(t)
            lines.append(f"Dialogue: 0,{ts(start)},{ts(end)},Default,,0,0,0,,{' '.join(parts)}")
    return head + "\n".join(lines) + "\n", chunks


def build_srt(chunks):
    out = []
    for n, ch in enumerate(chunks, 1):
        end = ch[-1]["e"] + 0.1
        if n < len(chunks):
            end = min(end, chunks[n][0]["s"])
        out.append(f"{n}\n{srt_ts(ch[0]['s'])} --> {srt_ts(end)}\n{' '.join(x['w'] for x in ch)}\n")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("words", help="words.json from transcribe.py")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--style", choices=STYLES, default="pop")
    ap.add_argument("--font", default="Arial")
    ap.add_argument("--fontsize", type=int)
    ap.add_argument("--color", default="#FFFFFF")
    ap.add_argument("--highlight", default="#FFD400")
    ap.add_argument("--position", type=float, default=0.72, help="vertical position of captions, 0=top 1=bottom")
    ap.add_argument("--no-uppercase", action="store_true")
    ap.add_argument("--out", default="captions.ass")
    a = ap.parse_args()
    data = json.load(open(a.words, encoding="utf-8"))
    words = data["words"] if isinstance(data, dict) else data
    ass, chunks = build(words, a.width, a.height, a.style, a.font, a.fontsize, a.color, a.highlight,
                        position=a.position, uppercase=False if a.no_uppercase else None)
    open(a.out, "w", encoding="utf-8").write(ass)
    open(a.out.rsplit(".", 1)[0] + ".srt", "w", encoding="utf-8").write(build_srt(chunks))
    print(a.out)


if __name__ == "__main__":
    main()
