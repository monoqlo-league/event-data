"""対局記録のプレイヤー名を、決めたとおりに置き換える(.github/replace-players.json)。

例: 20260901-games2.csv の「CPU」を、やまどりぃ に置き換える。
「N位プレイヤー名」の列だけを見て、欄の中身がまったく同じときだけ置き換える。ほかの列・ほかの文字は変えない。
置き換えたファイルの名前を表示する(変えたものが無ければ何も書き換えない)。
"""
import csv
import io
import json
import os
import re

RULES = os.path.join(os.path.dirname(__file__), "replace-players.json")


def main():
    with open(RULES, encoding="utf-8") as f:
        rules = {k: v for k, v in json.load(f).items() if not k.startswith("_") and isinstance(v, dict)}
    for path, table in rules.items():
        if not os.path.exists(path):
            continue
        raw = open(path, "rb").read()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        newline = "\r\n" if "\r\n" in text else "\n"
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            continue
        cols = [i for i, h in enumerate(rows[0]) if re.fullmatch(r"\d位プレイヤー名", h.strip())]
        count = 0
        for r in rows[1:]:
            for i in cols:
                if i < len(r) and r[i].strip() in table:
                    r[i] = table[r[i].strip()]
                    count += 1
        if not count:
            continue
        out = io.StringIO()
        csv.writer(out, lineterminator=newline).writerows(rows)
        open(path, "wb").write((b"\xef\xbb\xbf" if bom else b"") + out.getvalue().encode("utf-8"))
        print(f"{path}: {count}か所を置き換えた")


if __name__ == "__main__":
    main()
