"""Small dependency-free renderer used by the Corvi terminal panel."""

RESET = "\x1b[0m"


def sgr_fg(color):
    return f"\x1b[38;2;{color[0]};{color[1]};{color[2]}m"


def sgr_bg(color):
    return f"\x1b[48;2;{color[0]};{color[1]};{color[2]}m"


def sprite_cols(sprite):
    return 16 if int(sprite) <= 5 else 20


def has_eyes(pose):
    return pose not in {"sleeping", "peek"}


def _art(pose, eyes, width, height):
    # A compact, deliberately recognizable crow: crown, eye, hooked beak,
    # folded wing, tail feathers, and feet. Keep this as text cells so it
    # remains dependency-free and works in the full-screen terminal UI.
    # Front-facing crow: filled head and wings make the silhouette read at a
    # glance even in a small terminal panel.
    art = [
        "      .-.      ",
        "    ( •ᴗ• )    ",
        "   <   ▾   >   ",
        "     /|||\\     ",
        "      /\\      ",
    ]
    if eyes == "closed":
        art[1] = "    ( −ᴗ− )    "
    if len(art) < 6:
        art = [line.center(width)[:width] for line in art]
        return (art + [" " * width] * height)[:height]
    if pose in {"coding", "thinking"}:
        art[5] = " /  .'   \\\\\\\\\\\\\\   `.     \\ "
    if pose in {"celebrating", "excited"}:
        art[5] = " \\  `.   ///////   .'     / "
    art = [line.center(width)[:width] for line in art]
    return (art + [" " * width] * height)[:height]


def render_stage(pose, scols, srows, sprite, eyes, dx, dy, stage=None, quad=True):
    width, height = max(1, int(scols)), max(1, int(srows))
    art = _art(pose, eyes, min(width, 32), height)
    cells = [[(" ", None, None) for _ in range(width)] for _ in range(height)]
    top = max(0, (height - len(art)) // 2 + int(dy))
    left = max(0, (width - len(art[0])) // 2 + int(dx))
    for r, line in enumerate(art):
        rr = top + r
        if rr >= height:
            continue
        for c, ch in enumerate(line):
            cc = left + c
            if 0 <= cc < width and ch != " ":
                # Keep the feather outline bright enough for dark Terminal
                # themes; the panel background is already deep navy.
                feather = (125, 137, 172)
                accent = (255, 190, 70) if ch in {"•", "⌄", "−"} else feather
                cells[rr][cc] = (ch, accent, None)
    return cells


def overlay(cells, items):
    out = [row[:] for row in cells]
    for r, c, text, color in items:
        if 0 <= r < len(out):
            for i, ch in enumerate(str(text)):
                if 0 <= c + i < len(out[r]):
                    out[r][c + i] = (ch, color, None)
    return out


def cells_to_ansi(cells, reset=RESET):
    lines = []
    for row in cells:
        line = ""
        last = None
        for ch, fg, bg in row:
            if fg != last:
                line += sgr_fg(fg) if fg else reset
                last = fg
            line += ch
        lines.append(line + reset)
    return lines
