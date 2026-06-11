#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
泛化 Pips (NYT) 骨牌謎題 solver。

輸入格式 (從 stdin 或檔案讀入)：

    # 盤面
    <row1>
    <row2>
    ...
    (空白行)
    # 限制
    <region代碼> <限制形式>
    ...
    (空白行)
    # 骨牌
    00 12 34 56 ...

盤面規格：
  - 空白字元或 '_' = 不放東西（盤面空缺）
  - '*'           = 該格要放牌，但沒有任何限制
  - 其他字元       = 該格屬於某個限制區，字元為區域代碼（相同字元＝同一區）
  - 某行較短 → 不足的尾端視同空白 padding

限制形式（四種）：
  - '='   區內所有格子點數必須「全部相等」
  - '>N'  區內點數總和 > N
  - '<N'  區內點數總和 < N
  - 'N'   區內點數總和 == N        （單格區時就等於「該格 == N」）

骨牌：一行，每個 2 字元 token = 一張骨牌的兩面點數 (0-6)。骨牌可翻轉。
"""

import sys
from collections import Counter

# ----------------------------- 解析輸入 -----------------------------


def parse_input(text):
    lines = text.split("\n")

    sections = {"盤面": [], "限制": [], "骨牌": []}
    current = None
    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        stripped = line.strip()
        if stripped.startswith("#"):
            name = stripped.lstrip("#").strip()
            current = name if name in sections else None
            continue
        if stripped == "":
            # 空白行 = 結束目前 section
            current = None
            continue
        if current is not None:
            sections[current].append(line)

    if not sections["盤面"]:
        raise ValueError('找不到 "# 盤面" 區段內容')
    if not sections["骨牌"]:
        raise ValueError('找不到 "# 骨牌" 區段內容')

    return sections


def build_board(board_lines):
    """回傳 (cells 清單[(r,c)], region_of{(r,c):code}, R, C)。"""
    R = len(board_lines)
    C = max((len(l) for l in board_lines), default=0)
    cells = []
    region_of = {}
    for r in range(R):
        line = board_lines[r]
        for c in range(C):
            ch = line[c] if c < len(line) else " "  # 行較短 → padding 空白
            if ch == " " or ch == "_":
                continue  # 空缺，不放
            cells.append((r, c))
            region_of[(r, c)] = ch  # '*' 或區域代碼
    return cells, region_of, R, C


def parse_constraints(con_lines):
    """code -> (kind, value)。kind ∈ {'eq','gt','lt','sum'}"""
    cons = {}
    for line in con_lines:
        parts = line.split()
        if not parts:
            continue
        code = parts[0]
        spec = parts[1] if len(parts) > 1 else ""
        if spec == "=":
            cons[code] = ("eq", None)
        elif spec.startswith(">"):
            cons[code] = ("gt", int(spec[1:]))
        elif spec.startswith("<"):
            cons[code] = ("lt", int(spec[1:]))
        elif spec == "":
            raise ValueError(f'限制 "{code}" 缺少限制形式')
        else:
            cons[code] = ("sum", int(spec))
    return cons


def parse_dominoes(dom_lines):
    toks = " ".join(dom_lines).split()
    dominoes = []
    for t in toks:
        if len(t) != 2 or not t.isdigit():
            raise ValueError(f'骨牌 token 格式錯誤："{t}"（需為兩個數字，如 23）')
        dominoes.append((int(t[0]), int(t[1])))
    return dominoes


# ----------------------------- 求解器 -----------------------------


class PipsSolver:
    def __init__(self, cells, region_of, cons, dominoes, max_solutions=100):
        self.cells = cells
        self.region_of = region_of
        self.cons = cons
        self.cellset = set(cells)
        self.max_solutions = max_solutions

        # 區域 -> 該區所有格子（只記錄「有限制」的區域；'*' 與無限制者略過）
        self.region_cells = {}
        for cell, code in region_of.items():
            if code in cons:
                self.region_cells.setdefault(code, []).append(cell)

        # 鄰接表
        self.adj = {cell: self._neighbors(cell) for cell in cells}

        self.dom_count = Counter(dominoes)
        self.dom_types = list(self.dom_count.keys())

        self.val = {cell: None for cell in cells}
        self.order = list(cells)  # row-major 掃描順序
        self.placements = []
        self.solutions = []
        self.capped = False

    def _neighbors(self, cell):
        r, c = cell
        out = []
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            n = (r + dr, c + dc)
            if n in self.cellset:
                out.append(n)
        return out

    # 驗證合理性（盤面格數 vs 骨牌格數、區域是否都有定義）
    def validate(self):
        msgs = []
        ncells = len(self.cells)
        ndom = sum(self.dom_count.values())
        if ncells != 2 * ndom:
            msgs.append(
                f"盤面有 {ncells} 格，但骨牌共 {ndom} 張（= {2*ndom} 格），數量不符。"
            )
        if ncells % 2 != 0:
            msgs.append(f"盤面格數為奇數（{ncells}），無法用 1x2 骨牌完全鋪滿。")
        # 區域代碼有出現在盤面，卻沒有限制定義（且非 '*'）
        used = {code for code in self.region_of.values() if code != "*"}
        undefined = used - set(self.cons.keys())
        if undefined:
            msgs.append(
                f"盤面出現代碼 {sorted(undefined)} 但「# 限制」未定義（將視為無限制）。"
            )
        return msgs

    def _region_ok(self, code):
        kind, v = self.cons[code]
        cl = self.region_cells[code]
        filled = [self.val[c] for c in cl if self.val[c] is not None]
        full = len(filled) == len(cl)
        if kind == "sum":
            s = sum(filled)
            if s > v:
                return False
            if full and s != v:
                return False
            return True
        if kind == "gt":  # 總和 > v
            if full:
                return sum(filled) > v
            return True  # 未填滿無法提前否定
        if kind == "lt":  # 總和 < v
            if sum(filled) >= v:  # 之後只會更大 → 可剪枝
                return False
            return True
        if kind == "eq":  # 全部相等
            return len(set(filled)) <= 1
        return True

    def _first_uncovered(self):
        for cell in self.order:
            if self.val[cell] is None:
                return cell
        return None

    def _check_touch(self, *cells):
        seen = set()
        for cell in cells:
            code = self.region_of[cell]
            if code in self.cons and code not in seen:
                seen.add(code)
                if not self._region_ok(code):
                    return False
        return True

    def solve(self):
        self._backtrack()
        return self.solutions

    def _backtrack(self):
        if self.capped:
            return
        cell = self._first_uncovered()
        if cell is None:
            self.solutions.append(list(self.placements))
            if len(self.solutions) >= self.max_solutions:
                self.capped = True
            return

        for nb in self.adj[cell]:
            if self.val[nb] is not None:
                continue
            for dt in self.dom_types:
                if self.dom_count[dt] <= 0:
                    continue
                a, b = dt
                orients = {(a, b), (b, a)}
                for va, vb in orients:
                    self.val[cell] = va
                    self.val[nb] = vb
                    self.dom_count[dt] -= 1
                    if self._check_touch(cell, nb):
                        self.placements.append((cell, nb, dt, (va, vb)))
                        self._backtrack()
                        self.placements.pop()
                    self.val[cell] = None
                    self.val[nb] = None
                    self.dom_count[dt] += 1
                    if self.capped:
                        return


# ----------------------------- 輸出 -----------------------------


def render_solution(placements, R, C, region_of):
    grid = [["  " for _ in range(C)] for _ in range(R)]
    for r in range(R):
        for c in range(C):
            if (r, c) in region_of:
                grid[r][c] = " ."  # 是格子但（理論上）會被填
            else:
                grid[r][c] = "  "  # 空缺
    for cell, nb, dt, (va, vb) in placements:
        grid[cell[0]][cell[1]] = "%2d" % va
        grid[nb[0]][nb[1]] = "%2d" % vb
    return "\n".join("".join(row).rstrip() for row in grid)


# ----------------------------- 出圖 -----------------------------


def _region_palette(region_of):
    """為每個區域代碼配一個淡色（pastel）。'*' 與空缺給中性灰。"""
    import colorsys

    codes = sorted({c for c in region_of.values() if c != "*"})
    pal = {}
    n = max(len(codes), 1)
    for i, code in enumerate(codes):
        h = (i / n + 0.13) % 1.0  # 平均分佈色相，偏移避開純紅
        r, g, b = colorsys.hls_to_rgb(h, 0.82, 0.45)  # 高亮度低飽和 → pastel
        pal[code] = (int(r * 255), int(g * 255), int(b * 255))
    pal["*"] = (228, 228, 230)
    return pal


def render_image(placements, R, C, region_of, path, tint=False, cell=92):
    """把一組解畫成 PNG。骨牌畫成圓角磚塊＋骰子點數。tint=True 時各區上淡色底。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  （略過出圖：找不到 Pillow，請先 pip install pillow）")
        return False

    GAP, PAD = 3, 24
    W = PAD * 2 + C * (cell + GAP)
    H = PAD * 2 + R * (cell + GAP)
    img = Image.new("RGB", (W, H), (250, 250, 250))
    d = ImageDraw.Draw(img)

    def topleft(r, c):
        return PAD + c * (cell + GAP), PAD + r * (cell + GAP)

    def rrect(xy, rad, **kw):
        d.rounded_rectangle(xy, radius=rad, **kw)

    # 1) （可選）區域淡色底
    if tint:
        pal = _region_palette(region_of)
        for (r, c), code in region_of.items():
            x, y = topleft(r, c)
            rrect(
                [x + 2, y + 2, x + cell - 2, y + cell - 2],
                16,
                fill=pal.get(code, (230, 230, 232)),
            )

    # 2) 骨牌磚塊
    DOM_FILL = (237, 239, 244) if not tint else None  # tint 時讓底色透出，只描邊
    DOM_EDGE = (96, 101, 118)
    DIV = (176, 180, 192)
    for cellp, nb, dt, (va, vb) in placements:
        (ar, ac), (br, bc) = cellp, nb
        ax, ay = topleft(ar, ac)
        bx, by = topleft(br, bc)
        x0, y0 = min(ax, bx), min(ay, by)
        x1, y1 = max(ax, bx) + cell, max(ay, by) + cell
        if tint:
            rrect([x0, y0, x1, y1], 20, outline=DOM_EDGE, width=5)
        else:
            rrect([x0, y0, x1, y1], 20, fill=DOM_FILL, outline=DOM_EDGE, width=5)
        if ac == bc:  # 直放
            my = (min(ay, by) + max(ay, by) + cell) // 2
            d.line([x0 + 14, my, x1 - 14, my], fill=DIV, width=3)
        else:  # 橫放
            mx = (min(ax, bx) + max(ax, bx) + cell) // 2
            d.line([mx, y0 + 14, mx, y1 - 14], fill=DIV, width=3)

    # 3) 骰子點數
    def pips(cx, cy, n, rad=8, col=(38, 40, 48)):
        o = cell // 4
        P = {
            0: [],
            1: [(0, 0)],
            2: [(-1, -1), (1, 1)],
            3: [(-1, -1), (0, 0), (1, 1)],
            4: [(-1, -1), (1, -1), (-1, 1), (1, 1)],
            5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)],
            6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)],
        }
        for dx, dy in P.get(n, []):
            d.ellipse(
                [
                    cx + dx * o - rad,
                    cy + dy * o - rad,
                    cx + dx * o + rad,
                    cy + dy * o + rad,
                ],
                fill=col,
            )

    for cellp, nb, dt, (va, vb) in placements:
        for (r, c), v in ((cellp, va), (nb, vb)):
            x, y = topleft(r, c)
            pips(x + cell // 2, y + cell // 2, v)

    img.save(path)
    return True


def main():
    import argparse

    ap = argparse.ArgumentParser(description="泛化 Pips 骨牌謎題 solver")
    ap.add_argument("input", nargs="?", help="題目檔（省略則從 stdin 讀）")
    ap.add_argument(
        "-i",
        "--image",
        nargs="?",
        const="solution",
        default=None,
        metavar="PREFIX",
        help="把解輸出成 PNG（檔名 PREFIX_1.png…，預設前綴 solution）",
    )
    ap.add_argument(
        "-t", "--tint", action="store_true", help="出圖時各限制區上淡色底，方便對照"
    )
    ap.add_argument(
        "-n", "--num-images", type=int, default=3, help="最多輸出幾組解的圖（預設 3）"
    )
    args = ap.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    sections = parse_input(text)
    cells, region_of, R, C = build_board(sections["盤面"])
    cons = parse_constraints(sections["限制"])
    dominoes = parse_dominoes(sections["骨牌"])

    solver = PipsSolver(cells, region_of, cons, dominoes)
    for m in solver.validate():
        print("⚠️ ", m)

    sols = solver.solve()

    if not sols:
        print("\n❌ 無解。")
        return

    if solver.capped:
        print(f"\n找到至少 {len(sols)} 組解（已達上限，可能更多）。")
    else:
        print(f"\n✅ 找到 {len(sols)} 組解。")

    show = min(len(sols), 3)
    for i in range(show):
        print(f"\n—— 解 {i+1} ——")
        print(render_solution(sols[i], R, C, region_of))
        print("骨牌：")
        for cell, nb, dt, (va, vb) in sols[i]:
            print(f"  [{dt[0]}|{dt[1]}]  {cell}={va}  {nb}={vb}")
    if len(sols) > show:
        print(f"\n（另有 {len(sols)-show} 組未顯示）")

    # 出圖
    if args.image is not None:
        print()
        nimg = min(len(sols), max(args.num_images, 1))
        for i in range(nimg):
            path = f"{args.image}_{i+1}.png"
            if render_image(sols[i], R, C, region_of, path, tint=args.tint):
                print(f"  🖼  已輸出 {path}")


if __name__ == "__main__":
    main()
