# STEP 387: TRACE GRAPHICAL LADDER LOGIC RENDERER
#
# Converts Rockwell ladder instruction text into structured
# components for graphical display.
#
# Initial support:
# XIC - Examine If Closed
# XIO - Examine If Open
# OTE - Output Energize
# OTL - Output Latch
# OTU - Output Unlatch
#
# Unsupported instructions are preserved as generic blocks.
# Parallel branches will be added in the next stage.


def parse_ladder_rung(logic):
    """
    Convert an L5X ladder rung into a list of instruction objects.

    Example:
        XIC(Start)XIO(Fault)OTE(Motor);

    Returns:
        [
            {"type": "XIC", "operand": "Start"},
            {"type": "XIO", "operand": "Fault"},
            {"type": "OTE", "operand": "Motor"}
        ]
    """

    instructions = []

    if not logic:
        return instructions

    position = 0
    length = len(logic)

    while position < length:

        # Ignore whitespace, rung terminators, and branch delimiters
        # temporarily. Branch topology is handled in a later step.
        if logic[position].isspace() or logic[position] in ";[],":
            position += 1
            continue

        start = position

        # Read instruction mnemonic.
        while position < length and (
            logic[position].isalnum() or logic[position] == "_"
        ):
            position += 1

        mnemonic = logic[start:position]

        if not mnemonic or position >= length or logic[position] != "(":
            # Preserve unexpected text rather than getting stuck.
            instructions.append({
                "type": "RAW",
                "operand": logic[start:start + 1]
            })
            position = start + 1
            continue

        # Read operands, respecting nested parentheses.
        position += 1
        operand_start = position
        depth = 1

        while position < length and depth > 0:
            if logic[position] == "(":
                depth += 1
            elif logic[position] == ")":
                depth -= 1

            position += 1

        operand_end = position - 1 if depth == 0 else position

        instructions.append({
            "type": mnemonic.upper(),
            "operand": logic[operand_start:operand_end]
        })

    return instructions

# STEP 403: PARSE LADDER LOGIC WHILE PRESERVING BRANCH STRUCTURE

def parse_ladder_structure(logic):
    """
    Parse Rockwell ladder text into a nested structure.

    Example:
        XIC(Start)[XIC(A),XIC(B)]OTE(Motor);

    Returns a sequence containing instructions and parallel branches.
    """

    if not logic:
        return []

    position = 0
    length = len(logic)

    def parse_sequence(stop_characters=None):
        nonlocal position

        if stop_characters is None:
            stop_characters = set()

        elements = []

        while position < length:
            char = logic[position]

            if char in stop_characters:
                break

            if char.isspace() or char == ";":
                position += 1
                continue

            if char == "[":
                position += 1
                branches = []

                while position < length:
                    branch = parse_sequence({",", "]"})
                    branches.append(branch)

                    if position >= length:
                        break

                    if logic[position] == ",":
                        position += 1
                        continue

                    if logic[position] == "]":
                        position += 1
                        break

                elements.append({
                    "kind": "branch",
                    "paths": branches
                })
                continue

            start = position

            while position < length and (
                logic[position].isalnum() or logic[position] == "_"
            ):
                position += 1

            mnemonic = logic[start:position]

            if not mnemonic or position >= length or logic[position] != "(":
                elements.append({
                    "kind": "raw",
                    "text": logic[start:start + 1]
                })
                position = start + 1
                continue

            position += 1
            operand_start = position
            depth = 1

            while position < length and depth:
                if logic[position] == "(":
                    depth += 1
                elif logic[position] == ")":
                    depth -= 1
                position += 1

            operand_end = position - 1 if depth == 0 else position

            elements.append({
                "kind": "instruction",
                "type": mnemonic.upper(),
                "operand": logic[operand_start:operand_end]
            })

        return elements

    return parse_sequence()

# STEP 511: IDENTIFY CHANGED LADDER INSTRUCTIONS.
# Compare instruction sequences while preserving branch structure.

def mark_ladder_changes(previous_elements, new_elements):
    from difflib import SequenceMatcher

    def signature(item):
        if item["kind"] == "instruction":
            return (
                "instruction",
                item["type"],
                item["operand"]
            )

        if item["kind"] == "branch":
            return ("branch",)

        return ("raw", item.get("text", ""))

    def mark(items, status):
        for item in items:
            if item["kind"] == "instruction":
                item["change_status"] = status

            elif item["kind"] == "branch":
                for path in item["paths"]:
                    mark(path, status)

    def compare_branch_paths(old_paths, new_paths):
        def path_signature(path):
            return tuple(signature(item) for item in path)

        matcher = SequenceMatcher(
            None,
            [path_signature(path) for path in old_paths],
            [path_signature(path) for path in new_paths],
            autojunk=False
        )

        for operation, i1, i2, j1, j2 in matcher.get_opcodes():
            if operation == "equal":
                for old_path, new_path in zip(
                    old_paths[i1:i2],
                    new_paths[j1:j2]
                ):
                    compare(old_path, new_path)

            elif operation == "delete":
                for path in old_paths[i1:i2]:
                    mark(path, "removed")

            elif operation == "insert":
                for path in new_paths[j1:j2]:
                    mark(path, "added")

            elif operation == "replace":
                old_group = old_paths[i1:i2]
                new_group = new_paths[j1:j2]

                if len(old_group) == len(new_group):
                    for old_path, new_path in zip(old_group, new_group):
                        compare(old_path, new_path)
                else:
                    for path in old_group:
                        mark(path, "removed")
                    for path in new_group:
                        mark(path, "added")

    def compare(previous, current):
        matcher = SequenceMatcher(
            None,
            [signature(item) for item in previous],
            [signature(item) for item in current],
            autojunk=False
        )

        for operation, old_start, old_end, new_start, new_end in matcher.get_opcodes():

            old_items = previous[old_start:old_end]
            new_items = current[new_start:new_end]

            # STEP 517: RECURSIVELY CHECK MATCHING BRANCHES.
            if operation == "equal":
                for old_item, new_item in zip(old_items, new_items):
                    if (
                        old_item["kind"] == "branch"
                        and new_item["kind"] == "branch"
                    ):
                        compare_branch_paths(
                            old_item["paths"],
                            new_item["paths"]
                        )
                    else:
                        mark([old_item], "unchanged")
                        mark([new_item], "unchanged")

            elif operation == "delete":
                mark(old_items, "removed")

            elif operation == "insert":
                mark(new_items, "added")

            elif operation == "replace":
                if (
                    len(old_items) == len(new_items) == 1
                    and old_items[0]["kind"] == "branch"
                    and new_items[0]["kind"] == "branch"
                    and len(old_items[0]["paths"]) == len(new_items[0]["paths"])
                ):
                    for old_path, new_path in zip(
                        old_items[0]["paths"],
                        new_items[0]["paths"]
                    ):
                        compare(old_path, new_path)

                elif (
                    len(old_items) == len(new_items) == 1
                    and old_items[0]["kind"] == "instruction"
                    and new_items[0]["kind"] == "instruction"
                ):
                    mark(old_items, "modified")
                    mark(new_items, "modified")

                else:
                    mark(old_items, "removed")
                    mark(new_items, "added")

    compare(previous_elements, new_elements)

    return previous_elements, new_elements

# STEP 404: SVG LADDER DRAWING ENGINE

from html import escape

# STEP 420: CALCULATE PARALLEL BRANCH LAYOUT

def calculate_branch_layout(elements, row_height=90):
    """
    Calculate the vertical layout of ladder logic,
    including parallel and nested branches.

    Returns a layout tree with row positions.
    """

    def layout_sequence(items):
        result = []
        total_rows = 1

        for item in items:

            if item["kind"] == "instruction":
                result.append({
                    "kind": "instruction",
                    "instruction": item,
                    "rows": 1
                })

            elif item["kind"] == "branch":

                paths = []
                branch_rows = 0

                for path in item["paths"]:
                    path_layout = layout_sequence(path)
                    paths.append(path_layout)
                    branch_rows += path_layout["rows"]

                result.append({
                    "kind": "branch",
                    "paths": paths,
                    "rows": max(1, branch_rows)
                })

                total_rows = max(total_rows, branch_rows)

        return {
            "kind": "sequence",
            "elements": result,
            "rows": total_rows,
            "height": total_rows * row_height
        }

    return layout_sequence(elements)

# STEP 422: PARALLEL BRANCH SVG RENDERER

def render_branch_svg(elements):
    """
    Render parallel and nested ladder branches as SVG.
    Supports XIC, XIO, OTE, OTL, and OTU symbols.
    """

    from html import escape

    CELL_WIDTH = 170
    ROW_HEIGHT = 90
    LEFT_RAIL = 20
    TOP_Y = 80

    output_types = {"OTE", "OTL", "OTU"}

        # STEP 499: CALCULATE INSTRUCTION WIDTH FROM TAG LENGTH.

    def instruction_width(item):
        operand = str(item.get("operand") or "")

        label_width = len(operand) * 8.5

        return max(CELL_WIDTH, label_width + 50)

        # STEP 501: CALCULATE SEQUENCE WIDTH USING TAG LENGTHS.
    # Return widths in pixels instead of fixed cell counts.

    def sequence_width(items):
        total_width = 0

        for item in items:
            if item["kind"] == "instruction":
                total_width += instruction_width(item)

            elif item["kind"] == "branch":
                longest_path = max(
                    (
                        sequence_width(path)
                        for path in item["paths"]
                    ),
                    default=0
                )

                total_width += (
                    CELL_WIDTH * 2 + longest_path
                )

        return total_width

    def sequence_rows(items):
        rows = 1
        for item in items:
            if item["kind"] == "branch":
                rows = max(
                    rows,
                    sum(sequence_rows(path) for path in item["paths"])
                )
        return rows

    # STEP 504: SIZE SVG CANVAS USING PIXEL-BASED LAYOUT.
    # sequence_width() already returns pixels.

    width = max(
        1200,
        LEFT_RAIL + sequence_width(elements) + 100
    )

    height = max(
            160,
        sequence_rows(elements) * ROW_HEIGHT + 100
    )

    right_rail = width - 20

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" '
        f'style="max-width:none;display:block;" '
        f'role="img" aria-label="Branched ladder rung">'
    ]

    def line(x1, y1, x2, y2):
        parts.append(
            f'<line x1="{x1}" y1="{y1}" '
            f'x2="{x2}" y2="{y2}" '
            f'stroke="#222" stroke-width="2"/>'
        )

    def draw_instruction(item, x, y):
        kind = item["type"]
        operand = item["operand"]

                # STEP 523: DRAW INSTRUCTION CHANGE HIGHLIGHT.
        # Green = added, red = removed, yellow = modified.

        change_colors = {
            "added": "#2EAD56",
            "removed": "#DC3545",
            "modified": "#E6AC00"
        }

        change_status = item.get("change_status", "unchanged")
        highlight_color = change_colors.get(change_status)

        if highlight_color:
            label_width = max(96, len(str(operand)) * 8.5 + 20)

            parts.append(
                f'<rect x="{x - label_width / 2}" y="{y - 55}" '
                f'width="{label_width}" height="90" rx="8" '
                f'fill="{highlight_color}" fill-opacity="0.15" '
                f'stroke="{highlight_color}" stroke-width="2"/>'
            )

        parts.append(
            f'<text x="{x}" y="{y - 35}" '
            f'text-anchor="middle" font-family="monospace" '
            f'font-size="14" fill="#222">{escape(operand)}</text>'
        )

        if kind in {"XIC", "XIO"}:
            line(x - 12, y - 16, x - 12, y + 16)
            line(x + 12, y - 16, x + 12, y + 16)

            if kind == "XIO":
                line(x - 15, y + 19, x + 15, y - 19)

            return 12

        if kind in output_types:
            parts.append(
                f'<path d="M {x - 13} {y - 21} '
                f'Q {x - 37} {y} {x - 13} {y + 21}" '
                f'fill="none" stroke="#222" stroke-width="2"/>'
            )
            parts.append(
                f'<path d="M {x + 13} {y - 21} '
                f'Q {x + 37} {y} {x + 13} {y + 21}" '
                f'fill="none" stroke="#222" stroke-width="2"/>'
            )

            symbol = {"OTE": "", "OTL": "L", "OTU": "U"}[kind]

            if symbol:
                parts.append(
                    f'<text x="{x}" y="{y + 6}" '
                    f'text-anchor="middle" font-family="monospace" '
                    f'font-size="18" fill="#222">{symbol}</text>'
                )

            return 30

        parts.append(
            f'<rect x="{x - 40}" y="{y - 22}" '
            f'width="80" height="44" fill="white" '
            f'stroke="#222" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{x}" y="{y + 5}" '
            f'text-anchor="middle" font-family="monospace" '
            f'font-size="13" fill="#222">{escape(kind)}</text>'
        )
        return 40

        # STEP 503: DRAW LADDER SEQUENCES WITH VARIABLE-WIDTH CELLS.

    def draw_sequence(items, start_x, y):
        cursor = start_x

        for item in items:

            # STEP 503A: DRAW INDIVIDUAL INSTRUCTIONS.

            if item["kind"] == "instruction":
                cell_width = instruction_width(item)
                center = cursor + cell_width / 2

                radius = draw_instruction(item, center, y)

                line(cursor, y, center - radius, y)
                line(center + radius, y, cursor + cell_width, y)

                cursor += cell_width

            # STEP 503B: DRAW PARALLEL AND NESTED BRANCHES.

            elif item["kind"] == "branch":
                paths = item["paths"]

                longest_path = max(
                    (sequence_width(path) for path in paths),
                    default=0
                )

                branch_width = CELL_WIDTH * 2 + longest_path

                split_x = cursor + CELL_WIDTH / 2
                join_x = cursor + branch_width

                path_y = y

                for path in paths:
                    line(split_x, path_y, split_x + 20, path_y)

                    end_x = draw_sequence(
                        path,
                        split_x + 20,
                        path_y
                    )

                    line(end_x, path_y, join_x, path_y)

                    path_y += sequence_rows(path) * ROW_HEIGHT

                bottom_y = path_y - ROW_HEIGHT

                line(cursor, y, split_x, y)
                line(split_x, y, split_x, bottom_y)
                line(join_x, y, join_x, bottom_y)

                cursor = join_x

        return cursor

    line(LEFT_RAIL, 15, LEFT_RAIL, height - 15)
    line(right_rail, 15, right_rail, height - 15)

    end_x = draw_sequence(elements, LEFT_RAIL, TOP_Y)
    line(end_x, TOP_Y, right_rail, TOP_Y)

    parts.append("</svg>")
    return "".join(parts)

def render_ladder_svg(logic, elements=None):
    """
    Render a simple Rockwell ladder rung as SVG.

    Returns None for branched rungs until branch
    rendering is implemented.
    """

    # STEP 419: ALLOW BRANCHED RUNGS INTO THE RENDERING PIPELINE
    if not logic:
        return None

    # STEP 513B: PRESERVE INSTRUCTION CHANGE STATUS.
    # Parse normally unless compared elements were supplied.

    if elements is None:
        elements = parse_ladder_structure(logic)

    # STEP 424: INITIALIZE INSTRUCTIONS BEFORE BRANCH ROUTING

    instructions = [
        item for item in elements
        if item["kind"] == "instruction"
    ]

    has_branches = any(
        item["kind"] == "branch"
        for item in elements
    )

    if has_branches:
        return render_branch_svg(elements)

    instructions = [
        item for item in elements
        if item["kind"] == "instruction"
    ]

    if not instructions or any(
        item["kind"] != "instruction" for item in elements
    ):
        return None

    # STEP 410: EXPAND SVG WIDTH FOR LONG TAG NAMES

    height = 130
    wire_y = 80
    left_rail = 20

    output_types = {"OTE", "OTL", "OTU"}

    input_count = sum(
        item["type"] not in output_types
        for item in instructions
    )

    output_count = sum(
        item["type"] in output_types
        for item in instructions
    )

    estimated_input_width = sum(
        max(125, len(item["operand"]) * 10 + 40)
        for item in instructions
        if item["type"] not in output_types
    )

    width = max(
        1200,
        estimated_input_width + output_count * 120 + 160
    )

    right_rail = width - 20

    output_types = {"OTE", "OTL", "OTU"}
    outputs = [
        item for item in instructions
        if item["type"] in output_types
    ]
    inputs = [
        item for item in instructions
        if item["type"] not in output_types
    ]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" '
        f'style="max-width:none; display:block;" role="img" '
        f'aria-label="Ladder logic rung">'
    ]

    def line(x1, y1, x2, y2):
        parts.append(
            f'<line x1="{x1}" y1="{y1}" '
            f'x2="{x2}" y2="{y2}" '
            f'stroke="#222" stroke-width="2"/>'
        )

    # STEP 414: PREVENT LONG OUTPUT TAGS FROM CLIPPING

    def label(x, text):
        estimated_width = len(text) * 9

        if x + estimated_width / 2 > right_rail - 10:
            anchor = "end"
            label_x = right_rail - 10
        else:
            anchor = "middle"
            label_x = x

        parts.append(
            f'<text x="{label_x}" y="45" text-anchor="{anchor}" '
            f'font-family="monospace" font-size="15" '
            f'fill="#222">{escape(text)}</text>'
        )

    def draw_instruction(item, x):
        kind = item["type"]
        operand = item["operand"]
        
        # STEP 514: HIGHLIGHT CHANGED LADDER INSTRUCTIONS.
        # Green = added, red = removed, yellow = modified.
        # Unchanged instructions retain their original appearance.

        change_colors = {
            "added": "#2EAD56",
            "removed": "#DC3545",
            "modified": "#E6AC00"
        }

        change_status = item.get("change_status", "unchanged")
        highlight_color = change_colors.get(change_status)

        # STEP 515: HIGHLIGHT CHANGED STRAIGHT-RUNG INSTRUCTIONS.
        # Green = added, red = removed, yellow = modified.

        change_colors = {
            "added": "#2EAD56",
            "removed": "#DC3545",
            "modified": "#E6AC00"
        }

        change_status = item.get("change_status", "unchanged")
        highlight_color = change_colors.get(change_status)

        if highlight_color:
            label_width = max(90, len(str(operand)) * 9)

            parts.append(
                f'<rect x="{x - label_width / 2 - 10}" y="25" '
                f'width="{label_width + 20}" height="83" rx="8" '
                f'fill="{highlight_color}" fill-opacity="0.15" '
                f'stroke="{highlight_color}" stroke-width="2"/>'
            )

        label(x, operand)

                # STEP 417: RESTORE XIC AND XIO CONTACT SYMBOLS

        if kind in {"XIC", "XIO"}:

            contact_half_width = 12
            contact_half_height = 16

            # Left contact bar
            line(
                x - contact_half_width,
                wire_y - contact_half_height,
                x - contact_half_width,
                wire_y + contact_half_height
            )

            # Right contact bar
            line(
                x + contact_half_width,
                wire_y - contact_half_height,
                x + contact_half_width,
                wire_y + contact_half_height
            )

            # XIO diagonal slash
            if kind == "XIO":
                line(
                    x - 15,
                    wire_y + 19,
                    x + 15,
                    wire_y - 19
                )

            return 12

        # STEP 416: ROCKWELL-STYLE OUTPUT COIL SYMBOLS

        if kind in output_types:

            # Two curved sides form the output coil.
            # Unlike an ellipse, the coil remains open in the middle.
            parts.append(
                f'<path d="M {x - 13} {wire_y - 21} '
                f'Q {x - 37} {wire_y} {x - 13} {wire_y + 21}" '
                f'fill="none" stroke="#222" stroke-width="2"/>'
            )

            parts.append(
                f'<path d="M {x + 13} {wire_y - 21} '
                f'Q {x + 37} {wire_y} {x + 13} {wire_y + 21}" '
                f'fill="none" stroke="#222" stroke-width="2"/>'
            )

            symbol = {
                "OTE": "",
                "OTL": "L",
                "OTU": "U"
            }[kind]

            if symbol:
                parts.append(
                    f'<text x="{x}" y="{wire_y + 6}" '
                    f'text-anchor="middle" '
                    f'font-family="monospace" font-size="18" '
                    f'fill="#222">{symbol}</text>'
                )

            return 30

        # Generic block for instructions not yet supported
        parts.append(
            f'<rect x="{x - 40}" y="{wire_y - 22}" '
            f'width="80" height="44" fill="white" '
            f'stroke="#222" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{x}" y="{wire_y + 5}" '
            f'text-anchor="middle" font-family="monospace" '
            f'font-size="13" fill="#222">{escape(kind)}</text>'
        )

        return 40

    # Left and right power rails
    line(left_rail, 15, left_rail, 115)
    line(right_rail, 15, right_rail, 115)

    cursor = left_rail

    # STEP 413: CONTINUOUS WIRING WITH SEPARATE LABEL SPACING

    previous_label_right = left_rail

    for item in inputs:
        radius = 40 if item["type"] not in {"XIC", "XIO"} else 12

        label_width = max(90, len(item["operand"]) * 9)

        # Keep labels separated without breaking the wire.
        center = max(
            cursor + radius + 35,
            previous_label_right + label_width / 2 + 25
        )

        # Wire connects directly to the instruction symbol.
        line(cursor, wire_y, center - radius, wire_y)

        draw_instruction(item, center)

        # Cursor tracks the actual end of the symbol.
        cursor = center + radius

        # Label spacing is tracked independently.
        previous_label_right = center + label_width / 2

    # Outputs positioned near the right rail
    if outputs:
        output_start = right_rail - 75 - (len(outputs) - 1) * 105

        for index, item in enumerate(outputs):
            center = output_start + index * 105
            line(cursor, wire_y, center - 30, wire_y)
            draw_instruction(item, center)
            cursor = center + 30

    line(cursor, wire_y, right_rail, wire_y)

    parts.append("</svg>")

    return "".join(parts)