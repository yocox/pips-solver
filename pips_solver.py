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
    """
    將原始題目文字解析成三個區段的字串清單。

    回傳 dict，鍵為 '盤面'、'限制'、'骨牌'，
    值為該區段每一行（不含標題行與空白行）的原始字串清單。
    若找不到必要區段則拋出 ValueError。
    """
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
    """
    將盤面字串清單轉換成格子座標與區域對照表。

    參數
    ----
    board_lines : list[str]
        '# 盤面' 區段的每一行原始字串。

    回傳
    ----
    cells : list[tuple[int,int]]
        所有需要放骨牌的格子座標 (row, col)，依 row-major 順序排列。
    region_of : dict[tuple[int,int], str]
        格子座標 → 區域代碼（'*' 表示無限制格）。
    R : int
        盤面列數。
    C : int
        盤面欄數（以最長行為準）。
    """
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
    """
    解析 '# 限制' 區段，回傳區域代碼到限制規格的對照表。

    回傳 dict：code -> (kind, value)
      - kind='eq'  : 區內所有格點數須相等，value=None
      - kind='gt'  : 區內點數總和 > value
      - kind='lt'  : 區內點數總和 < value
      - kind='sum' : 區內點數總和 == value

    若某行缺少限制形式則拋出 ValueError。
    """
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
    """
    解析 '# 骨牌' 區段，回傳骨牌清單。

    每個 2 字元 token（如 '23'）代表一張骨牌，兩個字元分別為兩面點數（0-6）。
    回傳 list[tuple[int,int]]，例如 [(2,3), (0,0), ...]。
    token 格式不符時拋出 ValueError。
    """
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
        """回傳與 cell 上下左右相鄰、且在盤面內的格子清單。"""
        r, c = cell
        out = []
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            n = (r + dr, c + dc)
            if n in self.cellset:
                out.append(n)
        return out

    def validate(self):
        """
        對題目進行基本合理性檢查，回傳警告訊息清單（無問題則為空列表）。

        檢查項目：
        - 盤面格數是否等於骨牌張數 × 2。
        - 盤面格數是否為偶數（奇數格無法完全鋪滿）。
        - 盤面出現的區域代碼是否都在 '# 限制' 中有定義。
        """
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
        """
        檢查指定區域的限制在目前已填入點數下是否仍可能成立。

        採用提前剪枝策略：
        - 'sum'：已填總和超過目標 → False；全填完且不等於目標 → False。
        - 'gt' ：全填完時才判斷總和是否 > 目標，否則保守回傳 True。
        - 'lt' ：已填總和 >= 目標則必定違反（後續只增不減）→ False。
        - 'eq' ：已出現兩種以上不同點數 → False。

        回傳 True 表示目前狀態仍合法（不代表最終一定可行）。
        """
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
        """
        依 row-major 順序找出第一個尚未填入點數的格子。

        回傳該格座標 (r, c)；若所有格子都已填滿則回傳 None（即找到一組完整解）。
        """
        for cell in self.order:
            if self.val[cell] is None:
                return cell
        return None

    def _check_touch(self, *cells):
        """
        在剛放下骨牌後，對骨牌所涉及的區域逐一執行限制檢查。

        參數 cells 為剛填入點數的格子（通常為骨牌的兩個格子）。
        對每個格子所屬的有限制區域呼叫 _region_ok()，
        同一區域只檢查一次（避免重複）。
        任一區域不合法即回傳 False，全部通過則回傳 True。
        """
        seen = set()
        for cell in cells:
            code = self.region_of[cell]
            if code in self.cons and code not in seen:
                seen.add(code)
                if not self._region_ok(code):
                    return False
        return True

    def solve(self):
        """
        啟動回溯搜尋，回傳所有找到的解。

        回傳 list[list[tuple]]，每個解為一組骨牌放置記錄：
            [(cell, nb, domino_type, (va, vb)), ...]
        其中 cell、nb 為骨牌佔據的兩個格子座標，
        domino_type 為該骨牌的正規形式（較小面在前），
        (va, vb) 為實際填入 cell 與 nb 的點數（考慮翻轉方向）。
        """
        self._backtrack()
        return self.solutions

    def _backtrack(self):
        """
        遞迴回溯核心。

        每次取出第一個未填格子，枚舉其所有相鄰空格作為骨牌搭檔，
        再枚舉可用骨牌類型與翻轉方向，放入點數後立即進行限制剪枝。
        合法則繼續遞迴，否則撤銷（backtrack）。
        找到完整解時記錄至 self.solutions；達到 max_solutions 上限後設旗停止搜尋。
        """
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
    """
    將一組解轉換成純文字盤面字串，方便在終端機中顯示。

    每個格子以兩個字元寬度呈現點數；空缺格子顯示為空白，
    已分配但尚未填入的格子（理論上不應發生）顯示為 ' .'。
    回傳以換行符連接的多行字串。
    """
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
    """
    為每個限制區域代碼產生一個 pastel 色（RGB tuple）。

    顏色依 HSL 色相環平均分佈（偏移 0.13 避開純紅），
    亮度高（0.82）、飽和度低（0.45），視覺上柔和易區分。
    '*'（無限制格）固定給中性淺灰 (228, 228, 230)。
    回傳 dict：code -> (R, G, B)。
    """
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
    """
    將一組解繪製成 PNG 圖片並存檔。

    繪製流程分三層：
      1. （可選，tint=True）各格子依所屬區域塗 pastel 色底。
      2. 骨牌磚塊：以圓角矩形框出每張骨牌的兩格，並畫中線分隔兩面。
      3. 骰子點數：依點數值在格子中心繪製對應排列的實心圓點。

    參數
    ----
    placements : list[tuple]
        solve() 回傳的骨牌放置記錄。
    R, C : int
        盤面列數與欄數。
    region_of : dict
        格子座標 → 區域代碼（用於 tint 配色）。
    path : str
        輸出 PNG 檔案路徑。
    tint : bool
        是否為各限制區上淡色底（預設 False）。
    cell : int
        每個格子的像素大小（預設 92）。

    回傳 True 表示成功；若 Pillow 未安裝則印出提示並回傳 False。
    """
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
        """回傳格子 (r, c) 左上角的像素座標 (x, y)。"""
        return PAD + c * (cell + GAP), PAD + r * (cell + GAP)

    def rrect(xy, rad, **kw):
        """在指定矩形範圍繪製圓角矩形，其餘參數傳遞給 ImageDraw.rounded_rectangle。"""
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
    DIV = (202, 212, 222)
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
            d.line([x0 + 14, my, x1 - 14, my], fill=DIV, width=2)
        else:  # 橫放
            mx = (min(ax, bx) + max(ax, bx) + cell) // 2
            d.line([mx, y0 + 14, mx, y1 - 14], fill=DIV, width=2)

    # 3) 骰子點數
    def pips(cx, cy, n, rad=8, col=(38, 40, 48)):
        """
        在格子中心 (cx, cy) 依照骰子慣例繪製 n 個點（0-6）。

        點的排列位置參考標準骰子佈局，以 cell//4 為偏移量決定間距。
        每個點以半徑 rad 的實心圓表示，顏色由 col 指定。
        """
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
    """
    命令列進入點。

    解析引數後依序執行：讀取題目 → 建立盤面 → 解析限制與骨牌 →
    驗證輸入 → 求解 → 印出結果 → （可選）輸出 PNG 圖片。
    """
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
